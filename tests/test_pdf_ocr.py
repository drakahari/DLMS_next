import json
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.services import ocr_screenshots, pdf_ocr
from tests.csrf_test_utils import csrf_token


def scanned_pdf_bytes(text="Question 1\nWhich protocol is secure?\nA. FTP\nB. SFTP\nCorrect answer: B"):
    image = Image.new("RGB", (850, 1100), "white")
    ImageDraw.Draw(image).multiline_text((70, 70), text, fill="black", spacing=8)
    output = BytesIO()
    image.save(output, "PDF", resolution=144)
    return output.getvalue()


def review_question(page=1):
    return {
        "number": page,
        "question": f"Question from page {page}?",
        "choices": [{"label": "A", "text": "No"}, {"label": "B", "text": "Yes"}],
        "correct_answers": ["B"],
        "answer_mode": "single",
        "status": "complete",
        "pages": [page],
    }


def ocr_line_observations(lines, *, source_width=800, source_height=1200):
    observations = []
    top = 20
    for line_id, item in enumerate(lines, 1):
        if isinstance(item, tuple):
            text, left = item
        else:
            text, left = item, 120
        observations.append({
            "source_id": "synthetic-region",
            "page_index": 0,
            "source_width": source_width,
            "source_height": source_height,
            "text": text,
            "bounding_box": {
                "left": left,
                "top": top,
                "width": max(20, min(600, len(text) * 9)),
                "height": 24,
            },
            "confidence": 92.0,
            "block_id": 1,
            "paragraph_id": 1,
            "line_id": line_id,
        })
        top += 34
    return observations


class PDFTextUsefulnessTests(unittest.TestCase):
    def test_committed_pdf_corpus_characterizes_digital_scanned_and_mixed_pages(self):
        root = Path(__file__).parent / "fixtures" / "ocr" / "pdf"
        digital = dlms._pdf_extract_pages(root / "selectable-text.pdf")
        scanned = dlms._pdf_extract_pages(root / "fully-scanned.pdf")
        mixed = dlms._pdf_extract_pages(root / "mixed-text-and-scan.pdf")
        ambiguous = dlms._pdf_extract_pages(root / "low-text-ambiguous.pdf")
        self.assertEqual([], [item["page"] for item in pdf_ocr.analyze_pdf_text_usefulness(digital) if item["ocr_candidate"]])
        self.assertEqual([1], [item["page"] for item in pdf_ocr.analyze_pdf_text_usefulness(scanned) if item["ocr_candidate"]])
        self.assertEqual([2], [item["page"] for item in pdf_ocr.analyze_pdf_text_usefulness(mixed) if item["ocr_candidate"]])
        self.assertEqual("ambiguous", pdf_ocr.analyze_pdf_text_usefulness(ambiguous)[0]["classification"])

    def test_repeated_margin_suppression_preserves_image_preflight_signal(self):
        pages = [
            {"page": 1, "lines": ["Shared header", "First useful body line"], "has_images": False},
            {"page": 2, "lines": ["Shared header"], "has_images": True},
        ]
        cleaned, _removed = dlms._pdf_suppress_repeated_margins(pages)
        self.assertFalse(cleaned[0]["has_images"])
        self.assertTrue(cleaned[1]["has_images"])

    def test_image_preflight_detects_images_nested_in_form_xobjects(self):
        page = {
            "/Resources": {
                "/XObject": {
                    "/Form1": {
                        "/Subtype": "/Form",
                        "/Resources": {
                            "/XObject": {"/Scan": {"/Subtype": "/Image"}}
                        },
                    }
                }
            }
        }
        self.assertTrue(dlms._smart_pdf_parser._pdf_page_has_images(page))

    def test_low_ambiguous_usable_and_blank_thresholds_are_explicit(self):
        low = pdf_ocr.analyze_page_text_usefulness(
            {"page": 1, "lines": [], "has_images": True}
        )
        blank = pdf_ocr.analyze_page_text_usefulness(
            {"page": 2, "lines": [], "has_images": False}
        )
        ambiguous = pdf_ocr.analyze_page_text_usefulness(
            {
                "page": 3,
                "lines": [
                    "Short but substantive heading text",
                    "A second meaningful line remains limited overall",
                ],
            }
        )
        usable = pdf_ocr.analyze_page_text_usefulness(
            {
                "page": 4,
                "lines": [
                    "This is a substantive selectable-text question with enough useful content.",
                    "These answer choices and explanations make the extraction clearly usable.",
                ],
            }
        )
        self.assertEqual("low", low["classification"])
        self.assertTrue(low["ocr_candidate"])
        self.assertEqual("blank", blank["classification"])
        self.assertFalse(blank["ocr_candidate"])
        self.assertEqual("ambiguous", ambiguous["classification"])
        self.assertTrue(ambiguous["ocr_candidate"])
        self.assertEqual("usable", usable["classification"])
        self.assertFalse(usable["ocr_candidate"])

    def test_selection_is_candidate_only_ordered_and_bounded(self):
        self.assertEqual([2, 5], pdf_ocr.validate_selected_pages(["5", "2", "5"], [2, 5]))
        with self.assertRaisesRegex(ValueError, "not eligible"):
            pdf_ocr.validate_selected_pages([3], [2, 5])
        with self.assertRaisesRegex(ValueError, "no more than 25"):
            pdf_ocr.validate_selected_pages(range(1, 27), range(1, 27))


class PDFTargetedRasterQuestionTests(unittest.TestCase):
    @staticmethod
    def _page(page, lines, styled, regions):
        return {
            "page": page,
            "lines": lines,
            "styled_lines": [
                {"text": text, "y": y, "fragments": []}
                for text, y in styled
            ],
            "raster_regions": regions,
            "page_width": 612.0,
            "page_height": 792.0,
            "page_rotation": 0,
            "has_images": bool(regions),
        }

    @staticmethod
    def _region(*, left=110, bottom=330, right=500, top=610, pixels=(780, 560)):
        return {
            "left": float(left),
            "bottom": float(bottom),
            "right": float(right),
            "top": float(top),
            "pixel_width": pixels[0],
            "pixel_height": pixels[1],
        }

    def test_text_rich_page_targets_only_missing_question_raster(self):
        pages = [self._page(
            1,
            [
                "Question #1", "Which neutral configuration is valid?",
                "Question #2", "Which neutral value is direct?",
                "A. First", "B. Second",
            ],
            [("Question #1", 710), ("Question #2", 260)],
            [self._region()],
        )]
        parsed = dlms._pdf_parse_question_bank(pages)
        second_before = dict(parsed["questions"][1])

        candidates = dlms._pdf_targeted_ocr_candidates(pages, parsed)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["question_number"], 1)
        self.assertEqual(candidates[0]["page"], 1)
        self.assertEqual(candidates[0]["kind"], "choices")
        self.assertEqual(parsed["questions"][1], second_before)

    def test_repeated_decorative_raster_is_not_targeted(self):
        shared = self._region(left=150, bottom=350, right=460, top=455, pixels=(620, 210))
        pages = []
        for number in range(1, 5):
            lines = [f"Question #{number}", f"Neutral prompt {number}?"]
            if number > 1:
                lines.extend(["A. First", "B. Second"])
            pages.append(self._page(
                number,
                lines,
                [(f"Question #{number}", 700)],
                [dict(shared)],
            ))
        parsed = dlms._pdf_parse_question_bank(pages)

        self.assertEqual(
            dlms._pdf_targeted_ocr_candidates(pages, parsed),
            [],
        )

    def test_cross_page_raster_belongs_to_prior_question_not_neighbor(self):
        pages = [
            self._page(
                1,
                ["Question #10", "Which neutral block is valid?"],
                [("Question #10", 150)],
                [],
            ),
            self._page(
                2,
                [
                    "Question #11", "Which direct option is valid?",
                    "A. North", "B. South",
                ],
                [("Question #11", 180)],
                [self._region(bottom=250, top=700)],
            ),
        ]
        parsed = dlms._pdf_parse_question_bank(pages)

        candidates = dlms._pdf_targeted_ocr_candidates(pages, parsed)

        self.assertEqual(
            [(item["question_number"], item["page"]) for item in candidates],
            [(10, 2)],
        )
        self.assertEqual(
            [choice["text"] for choice in parsed["questions"][1]["choices"]],
            ["North", "South"],
        )

    def test_unassigned_end_matter_page_is_never_targeted(self):
        pages = [
            self._page(
                1,
                ["Question #1", "Which neutral block is valid?"],
                [("Question #1", 700)],
                [],
            ),
            self._page(2, ["Appendix", "Further resources"], [], [self._region()]),
        ]
        result = dlms._pdf_parse_question_bank(pages)
        result["unassigned_pages"] = [2]

        self.assertEqual(
            dlms._pdf_targeted_ocr_candidates(pages, result),
            [],
        )

    def test_standalone_labels_preserve_multiline_choice_bodies(self):
        observations = ocr_line_observations([
            ("A.", 60), ("mode alpha {", 130), ("enabled true", 150), ("}", 130),
            ("B.", 61), ("mode beta {", 130), ("enabled false", 150), ("}", 130),
            ("C.", 59), ("mode gamma {", 130), ("level 3", 150), ("}", 130),
            ("D.", 62), ("mode delta {", 130), ("level 4", 150), ("}", 130),
            ("E.", 60), ("mode epsilon {", 130), ("level 5", 150), ("}", 130),
        ])

        result = dlms._pdf_raster_question_parser.parse_targeted_raster_choices(
            observations
        )

        self.assertEqual(result["status"], "review")
        self.assertEqual([choice["label"] for choice in result["choices"]], list("ABCDE"))
        self.assertEqual(
            result["choices"][0]["text"],
            "mode alpha {\nenabled true\n}",
        )

    def test_missing_source_label_is_preserved_as_incomplete(self):
        observations = ocr_line_observations([
            ("A.", 60), ("alpha", 130),
            ("B.", 60), ("beta", 130),
            ("D.", 60), ("delta", 130),
            ("E.", 60), ("epsilon", 130),
        ])

        result = dlms._pdf_raster_question_parser.parse_targeted_raster_choices(
            observations
        )

        self.assertEqual(result["status"], "incomplete")
        self.assertEqual([choice["label"] for choice in result["choices"]], ["A", "B", "D", "E"])
        self.assertTrue(any("missing or noncontiguous" in issue for issue in result["issues"]))

    def test_misaligned_label_like_code_line_is_not_promoted_to_a_choice(self):
        observations = ocr_line_observations([
            ("A.", 60), ("alpha {", 130), ("i", 220), ("}", 130),
            ("B.", 61), ("beta {", 130), ("enabled true", 150), ("}", 130),
        ])

        result = dlms._pdf_raster_question_parser.parse_targeted_raster_choices(
            observations
        )

        self.assertEqual([choice["label"] for choice in result["choices"]], ["A", "B"])
        self.assertIn("i", result["choices"][0]["text"])

    def test_merge_deduplicates_selectable_text_and_never_adds_correctness(self):
        question = {
            "number": 3,
            "question": "Choose two neutral modes.",
            "choices": [{"label": "A", "text": "Alpha mode"}],
            "correct": "",
            "correct_answers": [],
            "answer_mode": "multiple",
            "pages": [1],
            "status": "incomplete",
            "issues": ["Fewer than two answer choices were detected."],
        }
        recovered = dlms._pdf_raster_question_parser.parse_targeted_raster_choices(
            ocr_line_observations([
                ("✓", 20),
                ("A.", 60), ("Alpha mode", 130),
                ("B.", 60), ("Beta mode", 130),
            ])
        )
        source = {
            "id": "abcdefghijkl",
            "kind": "choices",
            "page": 2,
            "question_number": 3,
        }

        merged = dlms._pdf_raster_question_parser.merge_targeted_raster_result(
            question, recovered, source
        )

        self.assertEqual([choice["label"] for choice in merged["choices"]], ["A", "B"])
        self.assertEqual(sum(choice["text"] == "Alpha mode" for choice in merged["choices"]), 1)
        self.assertEqual(merged["correct_answers"], [])
        self.assertEqual(merged["correct"], "")
        self.assertEqual(merged["answer_mode"], "multiple")
        self.assertTrue(merged["correctness_confirmation_required"])
        self.assertFalse(merged["correctness_confirmed"])
        self.assertIn("✓", merged["ocr_metadata"]["unassigned_text"])


class PDFRasterServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlms-pdf-ocr-service-")
        self.root = Path(self.temp.name)
        self.pdf = self.root / "source.pdf"
        self.pdf.write_bytes(scanned_pdf_bytes())
        pdf_ocr.stage_pdf_ocr_task(self.root / "stage", "abcdefghijkl", self.pdf)

    def tearDown(self):
        self.temp.cleanup()

    def test_selectable_extractor_records_painted_raster_geometry(self):
        page = dlms._pdf_extract_pages(self.pdf)[0]

        self.assertGreater(page["page_width"], 0)
        self.assertGreater(page["page_height"], 0)
        self.assertEqual(page["page_rotation"], 0)
        self.assertTrue(page["raster_regions"])
        region = page["raster_regions"][0]
        self.assertLess(region["left"], region["right"])
        self.assertLess(region["bottom"], region["top"])
        self.assertGreater(region["pixel_width"], 0)
        self.assertGreater(region["pixel_height"], 0)

    def test_selected_page_renders_near_300_dpi_and_preview_is_bounded(self):
        result = pdf_ocr.render_pdf_page(
            self.root / "stage",
            "abcdefghijkl",
            1,
            render_lock=threading.RLock(),
        )
        self.assertEqual(300.0, result["dpi"])
        self.assertLessEqual(result["width"], pdf_ocr.PDF_OCR_MAX_SIDE)
        self.assertLessEqual(result["width"] * result["height"], pdf_ocr.PDF_OCR_MAX_PIXELS)
        self.assertEqual(
            "page-0001.png",
            pdf_ocr.staged_page_path(self.root / "stage", "abcdefghijkl", 1).name,
        )

    def test_targeted_region_render_is_bounded_and_smaller_than_full_page(self):
        full = pdf_ocr.render_pdf_page(
            self.root / "stage",
            "abcdefghijkl",
            1,
            render_lock=threading.RLock(),
        )
        region = pdf_ocr.render_pdf_region(
            self.root / "stage",
            "abcdefghijkl",
            "mnopqrstuvwx",
            1,
            {"left": 40, "bottom": 260, "right": 380, "top": 520},
            render_lock=threading.RLock(),
        )

        self.assertLess(region["width"] * region["height"], full["width"] * full["height"])
        self.assertEqual(
            "region-mnopqrstuvwx.png",
            pdf_ocr.staged_region_path(
                self.root / "stage", "abcdefghijkl", "mnopqrstuvwx"
            ).name,
        )

    def test_invalid_page_and_cancel_leave_no_rendering_temporary(self):
        with self.assertRaisesRegex(ValueError, "out of range"):
            pdf_ocr.render_pdf_page(
                self.root / "stage",
                "abcdefghijkl",
                2,
                render_lock=threading.RLock(),
            )
        with self.assertRaises(InterruptedError):
            pdf_ocr.render_pdf_page(
                self.root / "stage",
                "abcdefghijkl",
                1,
                render_lock=threading.RLock(),
                cancel_requested=lambda: True,
            )
        self.assertFalse(list((self.root / "stage" / "abcdefghijkl").glob("*.rendering.png")))

    def test_pdfium_work_is_serialized_by_caller_owned_lock(self):
        lock = mock.MagicMock()
        lock.__enter__.return_value = lock
        lock.__exit__.return_value = False
        pdf_ocr.render_pdf_page(
            self.root / "stage", "abcdefghijkl", 1, render_lock=lock
        )
        lock.__enter__.assert_called_once()

    def test_cleanup_and_pruning_only_remove_marked_tasks(self):
        unrelated = self.root / "stage" / "unrelatedfolder"
        unrelated.mkdir()
        self.assertTrue(pdf_ocr.cleanup_pdf_ocr_task(self.root / "stage", "abcdefghijkl"))
        self.assertTrue(unrelated.is_dir())


class SelectivePDFOCRRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlms-pdf-ocr-route-")
        self.root = Path(self.temp.name)
        self.drafts = self.root / "drafts"
        self.banks = self.root / "banks"
        self.staging = self.root / "uploads" / "ocr_pdfs"
        self.runtime = mock.Mock(version="5.5.3")
        self.patchers = [
            mock.patch.object(dlms, "PDF_IMPORT_DRAFT_FOLDER", str(self.drafts)),
            mock.patch.object(dlms, "PDF_QUESTION_BANK_FOLDER", str(self.banks)),
            mock.patch.object(dlms, "PDF_OCR_STAGING_FOLDER", str(self.staging)),
            mock.patch.object(dlms._ocr_service, "detect_tesseract_runtime", return_value=self.runtime),
        ]
        for patcher in self.patchers:
            patcher.start()
        dlms.OCR_SCREENSHOT_CANCELLATIONS = ocr_screenshots.OCRTaskCancellationRegistry()
        self.client = dlms.app.test_client()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def analyze_with_pages(self, pages, content_type="question_bank"):
        with mock.patch.object(dlms, "_pdf_extract_pages", return_value=pages), mock.patch.object(
            dlms, "_pdf_suppress_repeated_margins", side_effect=lambda value: (value, [])
        ), mock.patch.object(
            dlms, "_pdf_parse_question_bank", return_value={"questions": [review_question(1)], "summary": {"detected": 1, "complete": 1, "review": 0, "incomplete": 0}}
        ):
            return self.client.post(
                "/pdf-import/analyze",
                data={
                    "pdf_file": (BytesIO(scanned_pdf_bytes()), "source.pdf"),
                    "pdf_content_type": content_type,
                    "rights_ok": "1",
                    "csrf_token": csrf_token(self.client, "/pdf-import"),
                },
                content_type="multipart/form-data",
            )

    def test_digital_pdf_stays_on_existing_direct_review_path(self):
        response = self.analyze_with_pages(
            [{"page": 1, "lines": ["A long selectable-text question with enough useful words to be reliable.", "A. First answer and B. second answer with explicit explanatory content."], "has_images": False}]
        )
        self.assertEqual(302, response.status_code)
        self.assertIn("/pdf-import/review/", response.headers["Location"])
        self.assertNotIn("/ocr/", response.headers["Location"])

    def test_targeted_region_augments_known_question_without_duplicate(self):
        region = {
            "left": 100.0,
            "bottom": 330.0,
            "right": 500.0,
            "top": 610.0,
            "pixel_width": 800,
            "pixel_height": 560,
        }
        pages = [{
            "page": 1,
            "lines": [
                "Question #1", "Which neutral configuration is valid?",
                "Question #2", "Which direct value is valid?", "A. North", "B. South",
            ],
            "styled_lines": [
                {"text": "Question #1", "y": 710.0, "fragments": []},
                {"text": "Question #2", "y": 250.0, "fragments": []},
            ],
            "raster_regions": [region],
            "page_width": 612.0,
            "page_height": 792.0,
            "page_rotation": 0,
            "has_images": True,
        }]
        with mock.patch.object(
            dlms, "_pdf_extract_pages", return_value=pages
        ), mock.patch.object(
            dlms, "_pdf_suppress_repeated_margins", side_effect=lambda value: (value, [])
        ):
            response = self.client.post(
                "/pdf-import/analyze",
                data={
                    "pdf_file": (BytesIO(scanned_pdf_bytes()), "synthetic.pdf"),
                    "pdf_content_type": "question_bank",
                    "rights_ok": "1",
                    "csrf_token": csrf_token(self.client, "/pdf-import"),
                },
                content_type="multipart/form-data",
            )

        self.assertIn("/process", response.headers["Location"])
        draft_id = response.headers["Location"].split("/ocr/", 1)[1].split("/", 1)[0]
        draft = dlms._load_pdf_import_draft(draft_id)
        self.assertTrue(draft["targeted_ocr"])
        self.assertEqual(len(draft["questions"]), 2)
        self.assertEqual(draft["ocr_batch"]["sources"][0]["source_type"], "question_region")

        observations = ocr_line_observations([
            ("A.", 60), ("mode alpha", 130),
            ("B.", 60), ("mode beta", 130),
        ])
        rendered = {
            "page": 1,
            "filename": "region-synthetic.png",
            "mime_type": "image/png",
            "width": 800,
            "height": 1200,
            "dpi": 300.0,
        }
        with mock.patch.object(
            dlms, "_render_pdf_ocr_region", return_value=rendered
        ), mock.patch.object(
            dlms, "_recognize_rendered_pdf_page", return_value=observations
        ), mock.patch.object(
            dlms._ocr_question_parser, "infer_screenshot_questions"
        ) as full_page_inference:
            token = csrf_token(self.client, f"/pdf-import/ocr/{draft_id}/process")
            processed = self.client.post(
                f"/pdf-import/ocr/{draft_id}/process/next",
                headers={"Accept": "application/json", "X-CSRFToken": token},
            )

        self.assertEqual(processed.status_code, 200)
        full_page_inference.assert_not_called()
        updated = dlms._load_pdf_import_draft(draft_id)
        self.assertEqual(len(updated["questions"]), 2)
        self.assertEqual(
            [choice["text"] for choice in updated["questions"][0]["choices"]],
            ["mode alpha", "mode beta"],
        )
        self.assertEqual(
            [
                choice["text"]
                for choice in updated["questions"][1]["choices"]
                if choice["text"]
            ],
            ["North", "South"],
        )
        self.assertEqual(
            updated["questions"][1]["question"],
            "Which direct value is valid?",
        )
        self.assertEqual(updated["questions"][0]["correct_answers"], [])
        self.assertEqual(updated["questions"][0]["pages"], [1])
        review = self.client.get(
            f"/pdf-import/review/{draft_id}"
        ).get_data(as_text=True)
        self.assertIn("Selectable question text remained authoritative", review)
        self.assertIn("PDF page 1", review)

    def test_scanned_and_mixed_pdf_offer_only_low_text_pages(self):
        pages = [
            {"page": 1, "lines": ["A long normal question page with plenty of selectable embedded text.", "The answer choices and explanation make this page safely usable as direct text."], "has_images": False},
            {"page": 2, "lines": [], "has_images": True},
        ]
        response = self.analyze_with_pages(pages)
        self.assertIn("/pdf-import/ocr/", response.headers["Location"])
        draft_id = response.headers["Location"].rsplit("/", 1)[-1]
        draft = dlms._load_pdf_import_draft(draft_id)
        self.assertEqual([2], draft["pdf_ocr_preflight"]["candidate_pages"])
        self.assertTrue((self.staging / draft_id / pdf_ocr.PDF_OCR_SOURCE_FILENAME).is_file())
        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn('value="2"', page)
        self.assertNotIn('value="1"', page)

    def test_glossary_selectable_text_behavior_does_not_offer_ocr(self):
        response = self.analyze_with_pages(
            [{"page": 1, "lines": ["Term Definition"], "has_images": True}],
            content_type="glossary",
        )
        self.assertNotIn("/ocr/", response.headers["Location"])

    def test_unavailable_runtime_reports_offer_but_normal_pdf_remains_usable(self):
        diagnostic = mock.Mock(
            guidance=(
                "Source-mode OCR requires Tesseract 5 on PATH or configured with "
                "DLMS_TESSERACT_EXECUTABLE."
            )
        )
        with mock.patch.object(
            dlms._ocr_service, "detect_tesseract_runtime", return_value=None
        ), mock.patch.object(
            dlms._ocr_service, "diagnose_tesseract_runtime", return_value=diagnostic
        ):
            response = self.analyze_with_pages([{"page": 1, "lines": [], "has_images": True}])
            body = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn("OCR unavailable", body)
        self.assertIn("selectable text only", body)
        self.assertIn("PDF and terminology import", body)
        self.assertIn("DLMS_TESSERACT_EXECUTABLE", body)
        self.assertNotIn("/usr/", body)

    def test_selection_removes_chosen_page_from_direct_parse_and_preserves_order(self):
        response = self.analyze_with_pages(
            [
                {"page": 1, "lines": ["A long normal embedded question and enough details for direct extraction.", "Another substantive explanation line for a usable page."], "has_images": False},
                {"page": 2, "lines": [], "has_images": True},
                {"page": 3, "lines": ["Short scanned overlay"], "has_images": True},
            ]
        )
        draft_id = response.headers["Location"].rsplit("/", 1)[-1]
        with mock.patch.object(
            dlms,
            "_pdf_parse_question_bank",
            side_effect=lambda pages: {"questions": [review_question(page["page"]) for page in pages], "summary": {}},
        ) as parser:
            started = self.client.post(
                f"/pdf-import/ocr/{draft_id}/start",
                data={"ocr_pages": "2", "csrf_token": csrf_token(self.client, response.headers["Location"])},
            )
        self.assertEqual(302, started.status_code)
        self.assertEqual([1, 3], [page["page"] for page in parser.call_args.args[0]])
        draft = dlms._load_pdf_import_draft(draft_id)
        self.assertEqual([2], draft["pdf_ocr_preflight"]["selected_pages"])
        self.assertEqual([1, 3], [question["pages"][0] for question in draft["questions"]])

    def test_one_page_failure_is_partial_and_later_page_continues(self):
        response = self.analyze_with_pages(
            [{"page": 1, "lines": [], "has_images": True}, {"page": 2, "lines": [], "has_images": True}]
        )
        draft_id = response.headers["Location"].rsplit("/", 1)[-1]
        self.client.post(
            f"/pdf-import/ocr/{draft_id}/start",
            data={"ocr_pages": ["1", "2"], "csrf_token": csrf_token(self.client, response.headers["Location"])},
        )
        rendered = {"page": 2, "filename": "page-0002.png", "mime_type": "image/png", "width": 800, "height": 1000, "dpi": 300.0}
        with mock.patch.object(dlms, "_render_pdf_ocr_page", side_effect=[RuntimeError("render failed"), rendered]), mock.patch.object(
            dlms, "_recognize_rendered_pdf_page", return_value=(mock.Mock(source_width=800),)
        ), mock.patch.object(
            dlms._ocr_question_parser,
            "infer_screenshot_questions",
            return_value={"questions": [review_question(2)]},
        ):
            token = csrf_token(self.client, f"/pdf-import/ocr/{draft_id}/process")
            headers = {"Accept": "application/json", "X-CSRFToken": token}
            first = self.client.post(f"/pdf-import/ocr/{draft_id}/process/next", headers=headers)
            second = self.client.post(f"/pdf-import/ocr/{draft_id}/process/next", headers=headers)
        self.assertEqual(200, first.status_code)
        self.assertEqual(200, second.status_code)
        state = second.get_json()
        self.assertEqual("complete", state["status"])
        self.assertEqual(1, state["failed"])
        self.assertTrue(state["has_results"])

    def test_cancel_and_successful_save_remove_only_task_owned_staging(self):
        response = self.analyze_with_pages([{"page": 1, "lines": [], "has_images": True}])
        draft_id = response.headers["Location"].rsplit("/", 1)[-1]
        cancelled = self.client.post(
            f"/pdf-import/ocr/{draft_id}/cancel",
            data={"csrf_token": csrf_token(self.client, response.headers["Location"])},
        )
        self.assertEqual(302, cancelled.status_code)
        self.assertFalse((self.staging / draft_id).exists())

        response = self.analyze_with_pages([{"page": 1, "lines": [], "has_images": True}])
        draft_id = response.headers["Location"].rsplit("/", 1)[-1]
        draft = dlms._load_pdf_import_draft(draft_id)
        draft.update(
            {
                "source_kind": "user-provided-pdf-ocr",
                "questions": [
                    {
                        **review_question(1),
                        "correctness_confirmation_required": True,
                        "correctness_confirmed": False,
                        "ocr_metadata": {"page_number": 1, "source_type": "pdf_page"},
                    }
                ],
            }
        )
        dlms._save_pdf_import_draft(draft)
        payload = [{
            "index": 0,
            "question": "Which answer is correct?",
            "choices": [{"label": "A", "text": "No"}, {"label": "B", "text": "Yes"}],
            "answer_mode": "single",
            "correct_answers": ["B"],
            "correctness_confirmed": True,
            "explanation": "Yes is correct.",
            "feedback": {},
        }]
        saved = self.client.post(
            f"/pdf-import/save/{draft_id}",
            data={
                "quiz_title": "Scanned PDF Bank",
                "exam_minutes": "30",
                "review_payload": json.dumps(payload),
                "csrf_token": csrf_token(self.client),
            },
        )
        self.assertEqual(302, saved.status_code)
        bank = dlms._load_pdf_question_bank(saved.headers["Location"].rsplit("/", 1)[-1])
        self.assertEqual("user-provided-pdf-ocr", bank["source_kind"])
        self.assertNotIn("ocr_metadata", bank["questions"][0])
        self.assertFalse((self.staging / draft_id).exists())


if __name__ == "__main__":
    unittest.main()
