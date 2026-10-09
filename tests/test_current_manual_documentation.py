"""Prevent broken reader navigation and unsafe drift in current documentation."""
import html
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from dlms.routes.help import HELP_TOPIC_FILES

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / 'docs/user-manual'


def markdown_anchors(text):
    """GitHub-style heading fragments, including suffixes for repeated headings."""
    anchors, counts = set(), {}
    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', text, re.M):
        heading = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', heading)
        key = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        count = counts.get(key, 0)
        counts[key] = count + 1
        anchors.add(key + (f'-{count}' if count else ''))
    anchors.update(re.findall(r'\bid=["\']([^"\']+)["\']', text))
    return anchors


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links, self.ids, self.images = [], set(), []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if data.get('id'):
            self.ids.add(data['id'])
        if tag == 'a' and data.get('href'):
            self.links.append(data['href'])
        if tag == 'img':
            self.images.append(data)


class CurrentManualDocumentationTests(unittest.TestCase):
    def test_manual_relative_destinations_anchors_and_images(self):
        sources = [*MANUAL.glob('*.md'), ROOT / 'README.md', ROOT / 'docs/help-screenshots.md', ROOT / 'docs/releases/3.3.0.md']
        for path in sources:
            text = path.read_text()
            for match in re.finditer(r'(!?)\[([^]\n]*)\]\(([^)\n]+)\)', text):
                image, alt, target = match.groups()
                url = urlsplit(target.strip('<>'))
                if url.scheme or url.netloc:
                    continue
                # Repository GitHub navigation, not a nonexistent local output.
                if url.path == '../../releases':
                    continue
                destination = (path.parent / unquote(url.path)).resolve() if url.path else path
                with self.subTest(source=path.name, target=target):
                    self.assertTrue(destination.exists(), target)
                    if url.fragment and destination.suffix == '.md':
                        self.assertIn(unquote(url.fragment), markdown_anchors(destination.read_text()))
                    if image:
                        self.assertTrue(alt.strip(), 'Images need a meaningful alternative')

    def test_help_topic_destinations_and_fragments(self):
        client = dlms.app.test_client()
        pages = {}
        for topic in ('', *HELP_TOPIC_FILES, 'about', 'quiz-help', 'advanced-features'):
            response = client.get('/help/' + topic)
            try:
                self.assertEqual(response.status_code, 200)
                pages[('/help/' + topic).rstrip('/')] = Page(response.get_data(as_text=True))
            finally:
                response.close()
        for route, page in pages.items():
            for link in page.links:
                url = urlsplit(link)
                if url.scheme or url.netloc:
                    continue
                destination = url.path.rstrip('/') or route
                if not url.path or destination in pages:
                    with self.subTest(page=route, target=link):
                        if url.fragment:
                            self.assertIn(url.fragment, pages[destination].ids)
                if url.path.startswith('/help/'):
                    self.assertIn(destination, pages, (route, link))
            for image in page.images:
                with self.subTest(page=route, image=image.get('src')):
                    self.assertTrue(image.get('alt', '').strip())
                    if image.get('src', '').startswith('/static/'):
                        self.assertTrue((ROOT / image['src'].lstrip('/')).is_file())

    def test_every_destructive_action_has_help_scope_and_backup_exceptions(self):
        help_text = html.unescape((ROOT / 'static/help-maintenance.html').read_text())
        action_page = html.unescape((ROOT / 'templates/settings/reset-remove.html').read_text())
        # The same visible workflow must be discoverable in the safety guide.
        for label in ('Clear Saved Results from Database and Dashboard', 'Reset Learning Intelligence',
                      'Delete Study History', 'Reset Quiz Library & Results', 'Clear Imported / Source Content',
                      'Reset Application Settings', 'Reset DLMS to Fresh State', 'Remove DLMS Data from This Computer'):
            with self.subTest(action=label):
                self.assertIn(label, action_page)
                self.assertIn(label, help_text)
        self.assertIn('Clear Saved Results has no automatic backup', help_text)
        self.assertIn('Retained Study history does not rebuild the cleared estimates', help_text)
        self.assertIn('Restore replaces the profile; it does not merge', help_text)
        self.assertIn('Replacing the binary alone does not undo the database upgrade', help_text)
        self.assertIn('does not create an automatic recovery backup', help_text)

    def test_current_coverage_sources_exist(self):
        coverage = (MANUAL / 'UPDATE-COVERAGE-3.3.0.md').read_text()
        for source in re.findall(r'`((?:app\.py|dlms/|templates/|static/)[^`]*)`', coverage):
            with self.subTest(source=source):
                self.assertTrue(list(ROOT.glob(source)), source)
        index = (MANUAL / 'README.md').read_text()
        for guide in ('exam-plans.md', 'certifications-and-training.md', 'UPDATE-COVERAGE-3.3.0.md'):
            self.assertIn(guide, index)
