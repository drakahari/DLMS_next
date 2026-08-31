import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import app as dlms


class _GeneratedQuizTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.script_start_tags = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self.script_start_tags += 1

    def handle_data(self, data):
        self.text.append(data)


class GeneratedQuizSecurityTests(unittest.TestCase):
    def _build(self, portal_title, quiz_title, jsonfile="quiz.json"):
        temp_dir = tempfile.TemporaryDirectory(prefix="dlms-generated-xss-")
        self.addCleanup(temp_dir.cleanup)
        output = Path(temp_dir.name) / "quiz.html"
        dlms.build_quiz_html(
            "quiz.html", jsonfile, str(output), portal_title, quiz_title,
            None, 17, 90,
        )
        return output.read_text(encoding="utf-8")

    def test_titles_are_safe_in_html_and_inline_javascript(self):
        attack = '</script><script>alert(1)</script>'
        image_attack = '<img src=x onerror=alert(1)>'
        punctuation = 'Quotes "double", apostrophe\'s, slash \\, newline\n& entity &lt;'
        quiz_title = attack + image_attack + punctuation + '\u2028separator\u2029'
        portal_title = image_attack + attack + punctuation

        generated = self._build(portal_title, quiz_title)

        self.assertNotIn(attack, generated)
        self.assertNotIn(image_attack, generated)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", generated)
        self.assertIn("\\u003c/script\\u003e", generated)
        self.assertIn("\\u2028", generated)
        self.assertIn("\\u2029", generated)

        assignment = re.search(r"window\.quiz_title = (.*);", generated)
        self.assertIsNotNone(assignment)
        self.assertEqual(json.loads(assignment.group(1)), quiz_title)

        parser = _GeneratedQuizTextParser()
        parser.feed(generated)
        rendered_text = "".join(parser.text)
        self.assertIn(portal_title, rendered_text)
        self.assertIn(quiz_title, rendered_text)
        self.assertEqual(parser.script_start_tags, 4)

    def test_generated_quiz_file_metadata_uses_json_serialization(self):
        jsonfile = 'quiz "name" \\ line\n</script>.json'
        generated = self._build("Portal", "Ordinary Quiz", jsonfile=jsonfile)
        assignment = re.search(r"const QUIZ_FILE = (.*);", generated)
        self.assertIsNotNone(assignment)
        self.assertEqual(json.loads(assignment.group(1)), f"/data/{jsonfile}")
        self.assertNotIn("</script>.json", generated)

    def test_choice_content_is_created_as_text_nodes(self):
        script = Path(dlms.STATIC_ROOT, "script.js").read_text(encoding="utf-8")
        render_block = script[
            script.index("function renderQuestion()"):
            script.index("function pointInHotspot")
        ]
        self.assertIn("labelElement.textContent", render_block)
        self.assertIn('document.createTextNode(` ${String(choice.text ?? "")}`)', render_block)
        self.assertNotIn("${choiceText}", render_block)
        self.assertNotRegex(render_block, r"innerHTML\s*=.*choice\.text")

    def test_related_imported_text_sinks_remain_explicitly_escaped(self):
        script = Path(dlms.STATIC_ROOT, "script.js").read_text(encoding="utf-8")
        self.assertIn('textEl.innerText = q.question || "";', script)
        self.assertIn("escapeHtml(q.explanation)", script)
        self.assertIn("escapeHtml(pair.explanation)", script)
        self.assertIn("escapeHtml(pair.left)", script)
        self.assertIn("escapeHtml(pairs[idx].right)", script)
        self.assertIn("escapeHtml(source.attribution)", script)
        self.assertIn("safeExternalUrl(source.url)", script)

    def test_return_navigation_uses_full_native_links_and_inactive_overlay_is_hidden(self):
        generated = self._build("Portal", "Navigation Test")
        self.assertIn('<a id="returnPortalBtn" href="/">', generated)
        self.assertIn('<a id="returnLibraryBtn" href="/library">', generated)
        self.assertNotIn('id="returnLibraryBtn" onclick=', generated)

        styles = Path(dlms.STATIC_ROOT, "style.css").read_text(encoding="utf-8")
        inactive_overlay = re.search(
            r"\.pause-overlay\s*\{(?P<body>.*?)\n\}", styles, re.DOTALL
        )
        active_overlay = re.search(
            r"\.pause-overlay\.show\s*\{(?P<body>.*?)\n\}", styles, re.DOTALL
        )
        self.assertIsNotNone(inactive_overlay)
        self.assertIsNotNone(active_overlay)
        self.assertIn("visibility: hidden", inactive_overlay.group("body"))
        self.assertIn("pointer-events: none", inactive_overlay.group("body"))
        self.assertIn("visibility: visible", active_overlay.group("body"))
        self.assertIn("pointer-events: auto", active_overlay.group("body"))


if __name__ == "__main__":
    unittest.main()
