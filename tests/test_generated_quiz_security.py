import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
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

    def test_generated_markup_helpers_preserve_exact_escaping_contract(self):
        text = 'Café & <tag> > "double" \'single\''
        self.assertEqual(
            'Café &amp; &lt;tag&gt; &gt; "double" \'single\'',
            dlms._html_text(text),
        )
        self.assertEqual(
            "Café &amp; &lt;tag&gt; &gt; &quot;double&quot; &#x27;single&#x27;",
            dlms._html_attribute(text),
        )
        self.assertEqual("", dlms._html_text(None))
        self.assertEqual("", dlms._html_attribute(0))

        inline_value = '</script><!-- comment --> & Café\u2028line\u2029end'
        serialized = dlms._json_for_inline_script(inline_value)
        self.assertEqual(json.loads(serialized), inline_value)
        self.assertIn("\\u003c/script\\u003e", serialized)
        self.assertIn("\\u003c!-- comment --\\u003e", serialized)
        self.assertIn("\\u0026", serialized)
        self.assertIn("\\u2028", serialized)
        self.assertIn("\\u2029", serialized)
        self.assertIn("Café", serialized)
        self.assertNotIn("</script", serialized)

    def test_app_helper_exports_remain_patchable_for_quiz_builder(self):
        temp_dir = tempfile.TemporaryDirectory(prefix="dlms-generated-patch-")
        self.addCleanup(temp_dir.cleanup)
        output = Path(temp_dir.name) / "quiz.html"

        with mock.patch.object(dlms, "_html_text", return_value="safe-text") as text_mock, \
             mock.patch.object(dlms, "_html_attribute", return_value="safe-attribute") as attribute_mock, \
             mock.patch.object(dlms, "_json_for_inline_script", return_value='"safe-json"') as json_mock:
            dlms.build_quiz_html(
                "quiz.html", "quiz.json", str(output), "Portal", "Quiz",
                "logo.png", 17, 90,
            )

        self.assertEqual(
            [mock.call("Portal"), mock.call("Quiz")],
            text_mock.call_args_list,
        )
        attribute_mock.assert_called_once_with("/user-static/logos/logo.png")
        self.assertEqual(
            [mock.call("Quiz"), mock.call("/data/quiz.json"), mock.call(17)],
            json_mock.call_args_list,
        )

    def test_generated_shell_preserves_exam_logo_and_client_global_contracts(self):
        temp_dir = tempfile.TemporaryDirectory(prefix="dlms-generated-contract-")
        self.addCleanup(temp_dir.cleanup)
        output = Path(temp_dir.name) / "quiz.html"

        with mock.patch.object(
            dlms, "normalize_exam_minutes", return_value=37
        ) as normalize:
            dlms.build_quiz_html(
                "ignored-name.html",
                "questions café.json",
                str(output),
                "DLMS Portal",
                "Unicode Café Quiz",
                "badge & logo.png",
                "quiz-id-17",
                "invalid-duration",
            )

        generated = output.read_text(encoding="utf-8")
        normalize.assert_called_once_with("invalid-duration")
        self.assertIn("window.examDurationMinutes = 37;", generated)
        self.assertIn('const QUIZ_FILE = "/data/questions café.json";', generated)
        self.assertIn('window.QUIZ_ID = "quiz-id-17";', generated)
        self.assertIn('<script src="/static/script.js"></script>', generated)
        self.assertEqual(4, generated.count('class="mode-badge"'))
        self.assertEqual(
            4,
            generated.count(
                'src="/user-static/logos/badge &amp; logo.png" class="mode-badge"'
            ),
        )

    def test_artifact_name_helpers_preserve_identity_and_safe_registry_rules(self):
        with mock.patch.object(
            dlms,
            "_generated_quiz_artifact_identity",
            return_value="1234567890_deadbeef",
        ):
            self.assertEqual(
                (
                    "mixed_quiz_1234567890_deadbeef.html",
                    "mixed_quiz_1234567890_deadbeef.json",
                ),
                dlms._generated_quiz_artifact_names(" Mixed Quiz! "),
            )

        self.assertEqual(
            ("stored.html", "stored.json"),
            dlms._quiz_artifact_names({"html": "stored.html"}),
        )
        for unsafe in ("", "../stored.html", "folder/stored.html", "stored.json"):
            with self.subTest(unsafe=unsafe):
                with self.assertRaisesRegex(ValueError, "unsafe or missing HTML"):
                    dlms._quiz_artifact_names({"html": unsafe})

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

    def test_provenance_rejects_empty_relative_and_local_dlms_urls(self):
        script = Path(dlms.STATIC_ROOT, "script.js").read_text(encoding="utf-8")
        url_block = script[
            script.index("function safeExternalUrl"):
            script.index("function safeProvenanceLabel")
        ]
        label_block = script[
            script.index("function safeProvenanceLabel"):
            script.index("function choiceStudyState")
        ]

        self.assertIn('if (!raw) return "";', url_block)
        self.assertIn("new URL(raw)", url_block)
        self.assertNotIn("window.location.href", url_block)
        self.assertIn('["http:", "https:"]', url_block)
        self.assertIn('hostname === "localhost"', url_block)
        self.assertIn("/^127", url_block)
        self.assertIn("url.origin === window.location.origin", url_block)
        self.assertIn("return url.href", url_block)
        self.assertIn("html?|json", label_block)
        self.assertIn("safeProvenanceLabel(source, sourceUrl)", script)
        self.assertRegex(script, r"const sourceLine = sourceUrl\s+\?")

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
