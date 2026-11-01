"""Bounded, inert certificate previews. Original attachments remain downloads."""
from base64 import b64encode
from hashlib import sha256
from io import BytesIO
import math
from PIL import Image

from .certifications import MAX_ATTACHMENT_BYTES, validate_attachment

MAX_SIDE = 1600
IMAGE_TYPES = frozenset({'image/png', 'image/jpeg', 'image/webp'})


def preview(content, mime, expected_sha256, page_number, *, render_lock):
    """Return one PNG page from verified stored bytes, without files or native IO."""
    if not content or len(content) > MAX_ATTACHMENT_BYTES or sha256(content).hexdigest() != expected_sha256:
        raise ValueError('The certificate is unavailable or failed its integrity check. Reattach a verified copy.')
    if mime not in IMAGE_TYPES | {'application/pdf'}:
        raise ValueError('This certificate type is unsupported. Use a PDF, PNG, JPEG or WebP document.')
    checked = validate_attachment(content)
    if mime in IMAGE_TYPES:
        if not isinstance(checked, tuple):
            raise ValueError('The certificate content does not match its recorded type.')
        if page_number != 1:
            raise IndexError('This image has only one page.')
        with Image.open(BytesIO(checked[1])) as image:
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            output = BytesIO()
            image.save(output, format='PNG')
            png = output.getvalue()
        pages = 1
    else:
        if checked != 'application/pdf':
            raise ValueError('The certificate content does not match its recorded type.')
        import pypdfium2 as pdfium
        # PDFium is not thread-safe. Share the existing OCR render lock.
        with render_lock:
            document = pdfium.PdfDocument(content)
            try:
                pages = len(document)
                if not 1 <= pages <= 1000:
                    raise ValueError('The certificate must contain 1–1,000 pages.')
                if not 1 <= page_number <= pages:
                    raise IndexError('The selected certificate page is out of range.')
                page = document[page_number - 1]
                try:
                    width, height = page.get_size()
                    if not all(math.isfinite(n) and 0 < n <= 1_000_000 for n in (width, height)):
                        raise ValueError('The certificate page cannot be displayed safely.')
                    scale = min(2.0, (MAX_SIDE - 1) / max(width, height))
                    bitmap = page.render(scale=scale)
                    try:
                        image = bitmap.to_pil()
                        try:
                            if max(image.size) > MAX_SIDE or image.width * image.height > MAX_SIDE ** 2:
                                raise ValueError('The certificate preview exceeds display limits.')
                            output = BytesIO()
                            image.save(output, format='PNG')
                            png = output.getvalue()
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            finally:
                document.close()
    return {'image': b64encode(png).decode('ascii'), 'page_number': page_number, 'pages': pages}
