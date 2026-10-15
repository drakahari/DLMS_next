"""Presentation contracts: guards, counts and destinations remain truthful."""
import os
import re
import tempfile
import unittest
from pathlib import Path

_TEMP = tempfile.TemporaryDirectory(prefix='dlms-ui-cleanup-')
os.environ['QUIZAPP_DATA_DIR'] = _TEMP.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from flask import render_template
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

class UICleanupTests(unittest.TestCase):
    def import_page(self, available=True):
        banks = [dict(id=f'bank-{n}', title=f'Sample bank {n}', source_name=f'sample-{n}.pdf', active_count=n, used_count=n, generated_count=n) for n in (0, 1, 2)]
        with dlms.app.test_request_context('/pdf-import'):
            return render_template('pdf_import/index.html', banks=banks, term_banks=banks,
                                   ocr_available=available, ocr_version='5.5.3', ocr_max_files=20,
                                   ocr_max_file_mib=10, ocr_max_batch_mib=40,
                                   ocr_unavailable_guidance='Install the supported local OCR runtime.')

    def test_bank_counts_and_management_boundaries(self):
        html = self.import_page()
        for count, word in ((0,'quizzes'), (1,'quiz'), (2,'quizzes')):
            self.assertEqual(html.count(f'{count} {word} generated'), 2)
        for control in ('pdfExpandBanks','pdfCollapseBanks','pdfManageBanks'):
            self.assertIn(f'id="{control}"', html)
        self.assertIn('Done Managing', html)
        self.assertIn('if(!window.confirm(message)) event.preventDefault()', html)
        self.assertIn('Existing quizzes generated from it will remain available.', html)
        self.assertIn('/pdf-import/bank/bank-1/delete', html)
        self.assertIn('/pdf-import/terms/bank-1/delete', html)
        self.assertIn('Delete bank', html)
        self.assertIn('id="savedBanks"', html)

    def test_ocr_states_and_rights_remain_enforced(self):
        available, unavailable = self.import_page(), self.import_page(False)
        self.assertIn('OCR available · Tesseract 5.5.3', available)
        self.assertIn('OCR unavailable', unavailable)
        self.assertIn('Install the supported local OCR runtime.', unavailable)
        self.assertIn('Normal selectable-text PDF import remains fully available.', unavailable)
        self.assertIn('name="screenshots"', unavailable)
        self.assertIn('multiple required disabled', unavailable)
        self.assertIn('name="rights_ok" required disabled', unavailable)
        for action in ('/pdf-import/analyze','/pdf-import/screenshots','/pdf-import/ocr-matching'):
            self.assertIn(f'action="{action}"', available)
        self.assertEqual(available.count('name="rights_ok" required'), 3)
        self.assertIn('Selectable text is always used first.', available)
        self.assertNotIn('Your existing parsers are untouched', available)

    def test_pdf_review_safeguards_and_exclusion_meaning(self):
        template = (ROOT/'templates/pdf_import/review-question-bank.html').read_text()
        for guard in ('data-review-reset-confirmation-on-edit="true"',
                      'data-review-require-explanation="false"',
                      'data-review-reject-duplicate-questions="false"',
                      'data-single-mode-safeguard=', 'data-pdf-role="correctness-confirmed"'):
            self.assertIn(guard, template)
        self.assertIn('Questions marked Delete are preserved in the bank as excluded', template)
        self.assertIn('formnovalidate>Start Over', template)
        self.assertIn('full correct-answer set', template)

    def test_recovery_status_does_not_invent_low_ocr_confidence(self):
        draft = dict(id='sample', source_name='sample', source_kind='user-provided-screenshot-ocr',
                     page_count=1, detection={'recovery_mode': True}, questions=[],
                     summary={}, unassigned_text=[], quiz_title='Sample', exam_minutes=30)
        with dlms.app.test_request_context('/pdf-import/review/sample'):
            screenshot = render_template('pdf_import/review-question-bank.html', draft=draft)
            draft['source_kind'] = 'user-provided-pdf'
            text_recovery = render_template('pdf_import/review-question-bank.html', draft=draft)
        self.assertNotIn('Automatic parsing confidence was low.', screenshot)
        self.assertIn('Compare OCR-derived text and choices', screenshot)
        self.assertIn('Automatic parsing confidence was low.', text_recovery)

    def test_anki_selectors_and_shared_outputs_remain_separate(self):
        index = (ROOT/'templates/anki/index.html').read_text()
        self.assertIn('Quiz to preview', index)
        self.assertIn('action="/anki/export/quiz"', index)
        self.assertIn('Export Anki deck (.apkg)', index)
        custom = (ROOT/'templates/anki/custom.html').read_text()
        for destination in ('/anki/custom','/anki/export/custom','/anki/printable'):
            self.assertIn(f'formaction="{destination}"', custom)
        self.assertIn('formtarget="_blank"', custom)
        self.assertIn('name="duplex_flip"', custom)
        self.assertIn('Print one duplex test sheet', custom)
        self.assertIn('href="#printableCards"', custom)
        self.assertIn('id="customAnkiForm"', custom)

    def test_refreshed_help_image_dimensions_match_every_reference(self):
        refreshed = {'dashboard.webp', 'pdf_import.webp', 'pdf-review-controls.webp',
                     'anki_tools.webp', 'anki-print-controls.webp'}
        references = []
        for page in (ROOT/'static').glob('help*.html'):
            for tag in re.findall(r'<img\b[^>]*>', page.read_text()):
                source = re.search(r'src="/static/help_assets/([^"]+)"', tag)
                if not source or source[1] not in refreshed:
                    continue
                width = re.search(r'width="(\d+)"', tag)
                height = re.search(r'height="(\d+)"', tag)
                self.assertIsNotNone(width, str(page))
                self.assertIsNotNone(height, str(page))
                with Image.open(ROOT/'static/help_assets'/source[1]) as image:
                    self.assertEqual(image.size, (int(width[1]), int(height[1])), str(page))
                references.append(source[1])
        self.assertGreaterEqual(references.count('dashboard.webp'), 2)
        self.assertEqual(set(references), refreshed)
