"""Synthetic certificate viewing preserves download and integrity boundaries."""
from base64 import b64decode
from contextlib import closing
from hashlib import sha256
from io import BytesIO
import threading
import unittest
from unittest import mock
import uuid

from PIL import Image
from pypdf import PdfWriter
from tests import test_study_sessions as foundation
from dlms.services import certificate_preview
from tests.certificate_pdf_fixtures import restricted_pdf
from dlms.services import certifications

dlms = foundation.dlms


class CertificatePreviewTests(unittest.TestCase):
    setUp = foundation.StudySessionTests.setUp
    choice = staticmethod(foundation.StudySessionTests.choice)
    publish = foundation.StudySessionTests.publish
    fingerprint = foundation.StudySessionTests.fingerprint

    def attachment(self, kind='pdf'):
        output = BytesIO()
        if kind == 'pdf':
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            writer.add_blank_page(width=792, height=612)
            writer.write(output)
            mime = 'application/pdf'
        else:
            Image.new('RGB', (80, 40), 'navy').save(output, kind.upper())
            mime = {'png': 'image/png', 'jpeg': 'image/jpeg', 'webp': 'image/webp'}[kind]
        content = output.getvalue()
        identifier = uuid.uuid4().hex
        with closing(dlms.get_db()) as conn, conn:
            conn.execute('INSERT INTO certification_attachments VALUES(?,?,?,?)',
                         (identifier, mime, sha256(content).hexdigest(), content))
        return identifier, mime, content

    def test_pdf_view_renders_only_selected_page_and_keeps_original_download(self):
        identifier, mime, content = self.attachment()
        original = self.client.get('/certifications/attachments/' + identifier)
        self.assertEqual(original.data, content)
        self.assertIn('attachment;', original.headers['Content-Disposition'])
        for number in (1, 2):
            response = self.client.get(f'/certifications/attachments/{identifier}/view?page={number}')
            self.assertEqual(response.status_code, 200)
            self.assertIn(f'Page {number} of 2'.encode(), response.data)
            self.assertIn(b'data:image/png;base64,', response.data)
            self.assertIn(b'Download certificate', response.data)
            self.assertNotIn(b'<iframe', response.data)
            self.assertNotIn(b'<object', response.data)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with closing(dlms.get_db()) as conn:
            self.assertEqual(conn.execute('SELECT content FROM certification_attachments WHERE id=?', (identifier,)).fetchone()[0], content)

    def test_supported_images_render_as_inert_png(self):
        for kind in ('png', 'jpeg', 'webp'):
            with self.subTest(kind=kind):
                identifier, mime, content = self.attachment(kind)
                response = self.client.get(f'/certifications/attachments/{identifier}/view')
                self.assertEqual(response.status_code, 200)
                rendered = certificate_preview.preview(content, mime, sha256(content).hexdigest(), 1,
                                                       render_lock=dlms.PDF_OCR_RENDER_LOCK)
                with Image.open(BytesIO(b64decode(rendered['image']))) as image:
                    self.assertEqual(image.format, 'PNG')
                    self.assertLessEqual(max(image.size), certificate_preview.MAX_SIDE)

    def test_passwordless_restricted_pdf_view_and_download_keep_original_bytes(self):
        for algorithm in ('RC4-128', 'AES-128', 'AES-256'):
            with self.subTest(algorithm=algorithm):
                content = restricted_pdf(algorithm=algorithm)
                self.assertEqual(certifications.validate_attachment(content), 'application/pdf')
                identifier = uuid.uuid4().hex
                digest = sha256(content).hexdigest()
                with closing(dlms.get_db()) as conn, conn:
                    conn.execute('INSERT INTO certification_attachments VALUES(?,?,?,?)',
                                 (identifier, 'application/pdf', digest, content))
                for page in (1, 2):
                    response = self.client.get(f'/certifications/attachments/{identifier}/view?page={page}')
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertIn(f'Page {page} of 2'.encode(), response.data)
                    self.assertIn(b'data:image/png;base64,', response.data)
                    self.assertNotIn(b'<iframe', response.data)
                downloaded = self.client.get(f'/certifications/attachments/{identifier}')
                self.assertEqual(downloaded.data, content)
                self.assertIn('attachment;', downloaded.headers['Content-Disposition'])
                self.assertEqual(downloaded.headers['Cache-Control'], 'no-store')
                with closing(dlms.get_db()) as conn:
                    row = conn.execute('SELECT sha256,content FROM certification_attachments WHERE id=?', (identifier,)).fetchone()
                self.assertEqual(tuple(row), (digest, content))

    def test_password_locked_or_active_restricted_pdf_cannot_be_previewed(self):
        for content in (restricted_pdf(password='synthetic-opening-password'), restricted_pdf(active=True)):
            with self.subTest(digest=sha256(content).hexdigest()):
                with self.assertRaises(ValueError):
                    certifications.validate_attachment(content)
                # A damaged/legacy stored record must not bypass upload validation.
                identifier = uuid.uuid4().hex
                with closing(dlms.get_db()) as conn, conn:
                    conn.execute('INSERT INTO certification_attachments VALUES(?,?,?,?)',
                                 (identifier, 'application/pdf', sha256(content).hexdigest(), content))
                response = self.client.get(f'/certifications/attachments/{identifier}/view')
                self.assertEqual(response.status_code, 400)
                self.assertIn(b'role="alert"', response.data)
                self.assertNotIn(b'data:image/png;base64,', response.data)

    def test_missing_unsupported_corrupt_and_invalid_pages_report_useful_errors(self):
        missing = self.client.get('/certifications/attachments/' + uuid.uuid4().hex + '/view')
        self.assertEqual(missing.status_code, 404)
        self.assertIn(b'Reattach a verified copy', missing.data)
        identifier, _, _ = self.attachment()
        for page in ('0', '3', '-1', '1.5', 'x', '10000', '\u0661'):
            with self.subTest(page=page):
                response = self.client.get(f'/certifications/attachments/{identifier}/view', query_string={'page': page})
                self.assertEqual(response.status_code, 400)
                self.assertIn(b'role="alert"', response.data)
        with closing(dlms.get_db()) as conn, conn:
            conn.execute('UPDATE certification_attachments SET mime=? WHERE id=?', ('text/html', identifier))
        unsupported = self.client.get(f'/certifications/attachments/{identifier}/view')
        self.assertEqual(unsupported.status_code, 415)
        self.assertIn(b'unsupported', unsupported.data)
        with closing(dlms.get_db()) as conn, conn:
            conn.execute('UPDATE certification_attachments SET mime=?,sha256=? WHERE id=?', ('application/pdf', '0'*64, identifier))
        corrupt = self.client.get(f'/certifications/attachments/{identifier}/view')
        self.assertEqual(corrupt.status_code, 400)
        self.assertIn(b'integrity check', corrupt.data)

    def test_render_failure_is_visible_without_native_diagnostics(self):
        identifier, _, _ = self.attachment()
        with mock.patch('pypdfium2.PdfDocument', side_effect=RuntimeError('/private/native/path')):
            response = self.client.get(f'/certifications/attachments/{identifier}/view')
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'preview could not be displayed', response.data)
        self.assertIn(b'Download certificate', response.data)
        self.assertNotIn(b'/private/native/path', response.data)

    def test_pdfium_uses_ocr_lock_and_rejects_unsafe_dimensions_before_render(self):
        identifier, mime, content = self.attachment()
        document = mock.MagicMock()
        document.__len__.return_value = 2
        document.__getitem__.return_value.get_size.return_value = (float('inf'), 10)
        lock = threading.RLock()
        def opened(*args):
            self.assertTrue(lock._is_owned())
            return document
        with mock.patch('pypdfium2.PdfDocument', side_effect=opened):
            with self.assertRaisesRegex(ValueError, 'safely'):
                certificate_preview.preview(content, mime, sha256(content).hexdigest(), 1, render_lock=lock)
        document.__getitem__.return_value.render.assert_not_called()
        document.__getitem__.return_value.close.assert_called_once()
        document.close.assert_called_once()
        with mock.patch('dlms.services.certificate_preview.preview', wraps=certificate_preview.preview) as render:
            self.assertEqual(self.client.get(f'/certifications/attachments/{identifier}/view').status_code, 200)
        self.assertIs(render.call_args.kwargs['render_lock'], dlms.PDF_OCR_RENDER_LOCK)
