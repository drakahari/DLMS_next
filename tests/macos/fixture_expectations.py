"""Ground truth for the exact handoff PNG, independently visible in its SVG.

tests/fixtures/ocr/dlms-question.svg is the source of ocr-question.png. Its
protocol question differs from the separate neutral TXT quiz's shape question.
No correctness marker appears in this PNG; do not infer a recorded answer.
"""
from html.parser import HTMLParser

SCREENSHOT_QUESTION = 'Which protocol secures web traffic?'
SCREENSHOT_CHOICES = {'A': 'FTP', 'B': 'HTTPS', 'C': 'Telnet', 'D': 'HTTP'}


def assert_screenshot_fields(fields):
    question = ' '.join(fields.get('question_0', '').split())
    assert SCREENSHOT_QUESTION in question, ('Screenshot question missing from OCR review', question)
    for label, text in SCREENSHOT_CHOICES.items():
        found = ' '.join(fields.get('choice_0_' + label, '').split())
        assert found == text, ('Screenshot choice changed', label, found)


class ReviewFields(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields = {}
        self.textarea = None

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        name = values.get('name')
        if tag == 'input' and name and 'value' in values:
            self.fields[name] = values['value']
        elif tag == 'textarea' and name:
            self.textarea = name
            self.fields[name] = ''

    def handle_data(self, data):
        if self.textarea is not None:
            self.fields[self.textarea] += data

    def handle_endtag(self, tag):
        if tag == 'textarea':
            self.textarea = None


def screenshot_review(html):
    review = ReviewFields()
    review.feed(html)
    assert_screenshot_fields(review.fields)
    return {name: review.fields[name] for name in ('question_0', *(f'choice_0_{label}' for label in SCREENSHOT_CHOICES))}
