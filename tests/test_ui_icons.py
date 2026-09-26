"""The shared UI icon sprite must stay local, decorative, and consistent."""

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms


ROOT = Path(dlms.__file__).parent
SPRITE_URL = "/static/icons.svg#"


class UiIconTests(unittest.TestCase):
    def test_sprite_is_local_and_all_references_resolve(self):
        sprite = ROOT / "static" / "icons.svg"
        symbols = {
            node.attrib["id"]
            for node in ET.parse(sprite).iter()
            if node.tag.endswith("symbol")
        }
        self.assertIn("settings", symbols)
        self.assertIn("learning", symbols)
        self.assertIn("other", symbols)
        self.assertNotRegex(sprite.read_text(), r'(?:href|src)="(?:https?:)?//|<script|<image|<text')

        references = 0
        for folder in (ROOT / "templates", ROOT / "static"):
            for path in (*folder.rglob("*.html"), *folder.rglob("*.js")):
                page = path.read_text()
                for symbol in re.findall(r'<use href="' + SPRITE_URL + r'([^"#]+)"', page):
                    if symbol == "${icon}":
                        continue  # nav-normalize.js fills this from fixed local IDs below.
                    with self.subTest(path=path.relative_to(ROOT), symbol=symbol):
                        self.assertIn(symbol, symbols)
                    references += 1
        self.assertGreater(references, 500)
        response = dlms.app.test_client().get("/static/icons.svg")
        self.assertEqual(response.status_code, 200)
        self.assertIn("image/svg+xml", response.content_type)

    def test_navigation_markup_uses_decorative_svg_and_text_labels(self):
        page = dlms.app.test_client().get("/").get_data(as_text=True)
        for href, label, symbol in (
            ("/", "Dashboard", "home"),
            ("/library", "Quiz Library", "library"),
            ("/upload", "Build Quiz", "build"),
            ("/study-packs", "Study Packs", "study"),
            ("/law", "Law Study", "law"),
            ("/history", "History", "history"),
            ("/dashboard", "Analytics", "analytics"),
            ("/anki", "Anki Tools", "anki"),
            ("/settings", "Settings", "settings"),
            ("/content-packs", "Content Packs", "content"),
            ("/admin/image-editor", "Image Study Editor", "image"),
            ("/help", "Help", "help"),
        ):
            with self.subTest(label=label):
                pattern = (
                    r'<a class="dashboard-nav-item[^\"]*" href="'
                    + re.escape(href)
                    + r'">\s*<svg[^>]*aria-hidden="true"[^>]*focusable="false"[^>]*>'
                    + r'<use href="'
                    + SPRITE_URL
                    + symbol
                    + r'"></use></svg>\s*<span>'
                    + re.escape(label)
                    + r'</span>'
                )
                self.assertRegex(page, pattern)
        self.assertNotRegex(page, r'<span class="dashboard-nav-icon">[^<]+</span>')

    def test_dashboard_cards_reuse_feature_symbols(self):
        page = dlms.app.test_client().get("/").get_data(as_text=True)
        for href, symbol in (
            ("/library", "library"), ("/upload", "build"),
            ("/study-packs", "study"), ("/it", "it"),
            ("/law", "law"), ("/history", "history"),
            ("/dashboard", "analytics"), ("/settings", "settings"),
        ):
            with self.subTest(href=href):
                self.assertRegex(
                    page,
                    r'<a class="dashboard-action-card" href="'
                    + re.escape(href)
                    + r'">\s*<div class="dashboard-action-icon[^>]*aria-hidden="true">'
                    + r'<svg[^>]*aria-hidden="true"[^>]*><use href="'
                    + SPRITE_URL + symbol + r'"></use></svg>',
                )

    def test_client_navigation_uses_same_local_sprite(self):
        source = (ROOT / "static" / "nav-normalize.js").read_text()
        self.assertIn('href="/static/icons.svg#${icon}"', source)
        self.assertIn('aria-hidden="true" focusable="false"', source)
        self.assertIn("item('settings','/settings','settings','Settings')", source)
        self.assertIn("item('other','/study-packs?domain_group=other','other','Other Studies')", source)
        self.assertNotRegex(source, r"item\([^\n]*'[⚙⌘⚖✚▤▣✎◇]'\s*,")

    def test_headings_and_action_controls_do_not_reintroduce_emoji(self):
        client = dlms.app.test_client()
        for route, symbol, label in (
            ("/settings", "settings", "Settings"),
            ("/settings/appearance", "palette", "Appearance"),
            ("/settings/ai", "ai", "AI Integration"),
            ("/settings/parsing", "puzzle", "Parsing"),
            ("/settings/backup", "save", "Backup &amp; Restore"),
        ):
            with self.subTest(route=route):
                page = client.get(route).get_data(as_text=True)
                self.assertRegex(
                    page,
                    r'<h1><svg class="dlms-icon dlms-inline-icon" aria-hidden="true" focusable="false">'
                    + r'<use href="' + SPRITE_URL + symbol + r'"></use></svg> '
                    + label + r'</h1>',
                )
        navigation = client.get("/settings/navigation").get_data(as_text=True)
        self.assertIn('/static/icons.svg#save', navigation)
        self.assertIn('Save Navigation</button>', navigation)
        self.assertNotIn('💾', navigation)
        self.assertNotIn('⚙️', client.get("/settings").get_data(as_text=True))

    def test_icon_colors_follow_theme_variables(self):
        css = (ROOT / "static" / "style.css").read_text()
        self.assertIn("--icon-blue: var(--theme-accent-text", css)
        self.assertIn("--icon-green: light-dark(", css)
        self.assertIn("--icon-orange: light-dark(", css)
        self.assertIn("--icon-purple: light-dark(", css)
        self.assertIn("--icon-cyan: light-dark(", css)
        self.assertIn(".dashboard-nav-icon,.dashboard-action-arrow { color:var(--theme-nav-muted", css)
        self.assertIn(".dashboard-nav-item.active .dashboard-nav-icon { color:var(--theme-accent-text", css)


if __name__ == "__main__":
    unittest.main()
