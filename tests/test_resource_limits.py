import io
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from PIL import Image
from werkzeug.datastructures import FileStorage, MultiDict

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


class ChunkStream:
    def __init__(self, total, fail_after=None):
        self.remaining = total
        self.fail_after = fail_after
        self.read_bytes = 0

    def read(self, size=-1):
        if self.fail_after is not None and self.read_bytes >= self.fail_after:
            raise OSError("synthetic save failure")
        if self.remaining <= 0:
            return b""
        amount = self.remaining if size < 0 else min(size, self.remaining)
        self.remaining -= amount
        self.read_bytes += amount
        return b"x" * amount


class FakePage:
    def __init__(self, text):
        self.text = text

    def extract_text(self, visitor_text=None):
        if visitor_text is not None:
            visitor_text(self.text, None, [0, 0, 0, 0, 0, 0], {}, 12)
        return self.text


class FakeReader:
    def __init__(self, pages, encrypted=False):
        self.pages = pages
        self.is_encrypted = encrypted


def compact_png(width, height):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b"")


class UploadResourceLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlms-resource-")
        self.addCleanup(self.temp.cleanup)

    def test_smart_pdf_declared_over_limit_is_rejected_before_save(self):
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_bounded_save_upload") as bounded_save:
            response = client.open(
                "/pdf-import/analyze", method="POST",
                environ_overrides={"CONTENT_LENGTH": str(dlms.PDF_IMPORT_MAX_BYTES + dlms.UPLOAD_MULTIPART_OVERHEAD_BYTES + 1)},
            )
        self.assertEqual(response.status_code, 413)
        bounded_save.assert_not_called()

    def test_smart_pdf_declared_just_under_limit_reaches_bounded_save(self):
        path = os.path.join(self.temp.name, "near-limit.pdf")
        upload = FileStorage(stream=io.BytesIO(b"%PDF-test"), filename="study.pdf", content_length=dlms.PDF_IMPORT_MAX_BYTES - 1)
        written = dlms._bounded_save_upload(upload, path, dlms.PDF_IMPORT_MAX_BYTES, "PDF")
        self.assertEqual(written, 9)
        self.assertEqual(Path(path).read_bytes(), b"%PDF-test")

    def test_missing_or_lying_content_length_cannot_bypass_bounded_save(self):
        path = os.path.join(self.temp.name, "bounded.bin")
        upload = FileStorage(stream=ChunkStream(2049), filename="large.bin", content_length=0)
        with self.assertRaises(dlms.UploadTooLargeError):
            dlms._bounded_save_upload(upload, path, 2048, "Test file")
        self.assertFalse(os.path.exists(path))

    def test_partial_file_is_removed_when_stream_save_fails(self):
        path = os.path.join(self.temp.name, "partial.bin")
        upload = FileStorage(stream=ChunkStream(4096, fail_after=1024), filename="partial.bin")
        with self.assertRaises(OSError):
            dlms._bounded_save_upload(upload, path, 8192, "Test file")
        self.assertFalse(os.path.exists(path))

    def test_general_quiz_upload_has_early_workflow_limit(self):
        response = dlms.app.test_client().open(
            "/process", method="POST",
            environ_overrides={
                "CONTENT_LENGTH": str(
                    dlms.QUIZ_TEXT_UPLOAD_MAX_BYTES + dlms.LOGO_UPLOAD_MAX_BYTES + dlms.UPLOAD_MULTIPART_OVERHEAD_BYTES + 1
                )
            },
        )
        self.assertEqual(response.status_code, 413)

    def test_large_non_file_field_and_excessive_part_count_are_rejected(self):
        client = dlms.app.test_client()
        token = csrf_token(client)
        large = client.post(
            "/api/theme",
            data={"csrf_token": token, "theme": "dark", "oversized": "x" * (dlms.app.config["MAX_FORM_MEMORY_SIZE"] + 1)},
            content_type="multipart/form-data",
        )
        try:
            self.assertEqual(large.status_code, 413)
        finally:
            large.request.input_stream.close()
            large.close()

        fields = [("csrf_token", token), ("theme", "dark")]
        fields.extend((f"field_{index}", "x") for index in range(dlms.app.config["MAX_FORM_PARTS"] + 1))
        too_many = client.post("/api/theme", data=MultiDict(fields), content_type="multipart/form-data")
        try:
            self.assertEqual(too_many.status_code, 413)
        finally:
            too_many.request.input_stream.close()
            too_many.close()


class PdfResourceLimitTests(unittest.TestCase):
    def _extract_with_reader(self, reader):
        with mock.patch("pypdf.PdfReader", return_value=reader):
            return dlms._pdf_extract_pages("unused.pdf")

    def test_page_count_limit_is_enforced_before_page_extraction(self):
        pages = mock.MagicMock()
        pages.__len__.return_value = dlms.PDF_IMPORT_MAX_PAGES + 1
        reader = FakeReader(pages)
        with self.assertRaisesRegex(dlms.PDFResourceLimitError, "page limit"):
            self._extract_with_reader(reader)
        pages.__iter__.assert_not_called()

    def test_total_extracted_text_limit_is_enforced(self):
        page_text = "x" * (2 * 1024 * 1024 - 1024)
        reader = FakeReader([FakePage(page_text) for _ in range(9)])
        with self.assertRaisesRegex(dlms.PDFResourceLimitError, "extracted-text limit"):
            self._extract_with_reader(reader)

    def test_normal_multi_page_pdf_text_is_preserved(self):
        pages = self._extract_with_reader(FakeReader([FakePage("Question 1\nA. One"), FakePage("Correct Answer: A")]))
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0]["lines"], ["Question 1", "A. One"])

    def test_encrypted_and_malformed_pdfs_fail_cleanly(self):
        with self.assertRaisesRegex(ValueError, "Encrypted PDFs are not supported"):
            self._extract_with_reader(FakeReader([], encrypted=True))
        path = os.path.join(tempfile.gettempdir(), "dlms-malformed-resource-test.pdf")
        Path(path).write_bytes(b"not a pdf")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with self.assertRaisesRegex(ValueError, "malformed|cannot be read"):
            dlms._pdf_extract_pages(path)


class ImageResourceLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dlms-image-resource-")
        self.addCleanup(self.temp.cleanup)

    def test_dimension_and_pixel_limits_reject_before_full_decode(self):
        dimension_path = os.path.join(self.temp.name, "wide.png")
        Path(dimension_path).write_bytes(compact_png(dlms.IMAGE_MAX_WIDTH + 1, 1))
        with self.assertRaisesRegex(ValueError, "dimensions exceed"):
            dlms._decode_raster_image(dimension_path)

        pixel_path = os.path.join(self.temp.name, "pixels.png")
        Path(pixel_path).write_bytes(compact_png(10_000, 8_001))
        with self.assertRaisesRegex(ValueError, "pixels"):
            dlms._decode_raster_image(pixel_path)

    def test_excessive_gif_frames_are_rejected(self):
        path = os.path.join(self.temp.name, "animated.gif")
        frames = [Image.new("RGB", (2, 2), (index % 255, (index * 3) % 255, (index * 7) % 255)) for index in range(dlms.IMAGE_MAX_FRAMES + 1)]
        frames[0].save(
            path, format="GIF", save_all=True, append_images=frames[1:],
            duration=10, disposal=2, optimize=False,
        )
        with self.assertRaisesRegex(ValueError, "frame limit"):
            dlms._decode_raster_image(path)

    def test_pillow_decompression_bomb_is_controlled(self):
        path = os.path.join(self.temp.name, "bomb.png")
        Path(path).write_bytes(compact_png(15_000, 15_000))
        with self.assertRaisesRegex(ValueError, "valid supported raster image"):
            dlms._decode_raster_image(path)


if __name__ == "__main__":
    unittest.main()
