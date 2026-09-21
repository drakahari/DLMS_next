"""Regression coverage for paste cleanup, re-preview state and diagnostic controls."""
import io
import itertools
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms
from dlms.parsing.quiz_text import parse_questions
from dlms.routes.quiz import authoring
from types import SimpleNamespace


SOURCE = "1. Pick one\nA. First\nB. Second\nCorrect Answer: A\n\n2. Pick two\nA. First\nB. Second\nCorrect Answer: AB"


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current = None
        self.textarea = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = (attrs.get("action"), {})
            self.forms.append(self.current)
        elif self.current and tag == "input" and attrs.get("name"):
            self.current[1][attrs["name"]] = attrs.get("value", "")
        elif self.current and tag == "textarea":
            self.textarea = attrs.get("name")
            self.current[1][self.textarea] = ""

    def handle_data(self, data):
        if self.current and self.textarea:
            self.current[1][self.textarea] += data

    def handle_endtag(self, tag):
        if tag == "textarea":
            self.textarea = None
        elif tag == "form":
            self.current = None


class PastePreviewHardeningTests(unittest.TestCase):
    def preview(self, data=None, cfg=None, render=False):
        config = cfg or {}
        deps = SimpleNamespace(
            load_portal_config=lambda: config,
            normalize_exam_minutes=dlms.normalize_exam_minutes,
            save_preview_logo=dlms.save_preview_logo,
            get_confidence_setting=lambda: config.get("show_confidence", True),
            analyze_confidence=dlms.analyze_confidence,
        )
        with dlms.app.test_request_context(
            "/preview_paste", method="POST", data=data or {"quiz_text": SOURCE}
        ):
            if render:
                return authoring.preview_paste(deps)
            with mock.patch.object(authoring, "render_template", side_effect=lambda _, **kw: kw):
                return authoring.preview_paste(deps)

    def test_presets_independent_combinations_and_disabled_regex_engine(self):
        source = "Page 4\n1. A wrap-\nped stem\nA. First\nB. Second\nCorrect Answer: A"
        flags = ("preset_number_prefix", "preset_headers", "preset_pdf_spacing")
        for enabled in (False, True):
            for selected in itertools.product((False, True), repeat=3):
                with self.subTest(engine=enabled, selected=selected):
                    data = {"quiz_text": source, **{k: "1" for k, v in zip(flags, selected) if v}}
                    text = self.preview(data, {"enable_regex_replace": enabled})["cleaned"]
                    self.assertEqual("1. " not in text, selected[0])
                    self.assertEqual("Page 4" not in text, selected[1])
                    self.assertEqual("wrapped stem" in text, selected[2])

    def test_manual_regex_still_requires_setting(self):
        data = {"quiz_text": SOURCE, "replace_rules": "First => Changed"}
        self.assertNotIn("Changed", self.preview(data)["cleaned"])
        self.assertIn("Changed", self.preview(data, {"enable_regex_replace": True})["cleaned"])

    def test_built_in_controls_available_without_manual_regex(self):
        with dlms.app.test_request_context("/paste"):
            body = dlms.render_template("quiz/paste.html", portal_title="DLMS", cfg={"enable_regex_replace": False})
        self.assertEqual(3, body.count('name="preset_'))
        self.assertNotIn('name="replace_rules"', body)

    def test_invisible_control_default_on_and_explicitly_off(self):
        for cfg, visible in (({}, True), ({"enable_show_invisibles": True}, True),
                             ({"enable_show_invisibles": False}, False)):
            with self.subTest(cfg=cfg):
                body = self.preview(cfg=cfg, render=True)
                self.assertEqual('onclick="toggleInvisible()"' in body, visible)
                self.assertEqual('id="visualPanel"' in body, visible)
                self.assertIn('onclick="toggleDiff()"', body)

    def test_numbered_questions_safe_with_wrapping_and_no_removal_suggestion(self):
        for extra in ({}, {"preset_pdf_spacing": "1"}):
            context = self.preview({"quiz_text": SOURCE, **extra})
            self.assertEqual(parse_questions(SOURCE), parse_questions(context["cleaned"]))
            self.assertFalse(any(s["preset"] == "preset_number_prefix" for s in context["smart_suggestions"]))
        # Explicit advanced removal retains its historical behavior, not a syntax migration.
        removed = self.preview({"quiz_text": SOURCE, "preset_number_prefix": "1"})
        self.assertNotIn("1. Pick", removed["cleaned"])
        self.assertIn("can merge questions", Path("templates/quiz/paste.html").read_text())

    def test_wrapping_does_not_join_lowercase_choices_or_answer_markers(self):
        source = "1. Stem\na) first\nb) second\ncorrect answer: b"
        context = self.preview({"quiz_text": source, "preset_pdf_spacing": "1"})
        self.assertEqual(parse_questions(source), parse_questions(context["cleaned"]))

    def test_apply_fix_preserves_state_and_does_not_resubmit_display_placeholder(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(dlms, "LOGO_TEMP_FOLDER", directory):
            name = "temp_123.png"
            Path(directory, name).write_bytes(b"retained reference")
            data = {
                "quiz_title": '<Title & "quotes">', "exam_minutes": "37",
                "temp_logo_name": name, "quiz_text": "Page 5\nREMOVE\n" + SOURCE,
                "strip_text": "REMOVE", "replace_rules": "First => Changed",
                "preset_number_prefix": "1", "preset_pdf_spacing": "1",
            }
            cfg = {"enable_regex_replace": True}
            body = self.preview(data, cfg, render=True)
            fixes = [fields for action, fields in Forms(body).forms if action == "/preview_paste"]
            self.assertTrue(fixes)
            fields = fixes[0]
            for key, value in data.items():
                self.assertEqual(value, fields[key], key)
            self.assertEqual("1", fields["preset_headers"])
            second = self.preview(fields, cfg)
            self.assertEqual(37, second["exam_minutes"])
            self.assertEqual(name, second["preview_logo_name"])
            self.assertNotIn("Page 5", second["cleaned"])
            final = next(fields for action, fields in Forms(self.preview(fields, cfg, render=True)).forms
                         if action == "/process_paste")
            self.assertEqual("37", final["exam_minutes"])
            self.assertEqual(name, final["temp_logo_name"])
            self.assertEqual(second["cleaned"], final["quiz_text"])
            empty = self.preview({"quiz_text": "Page 1\n"+SOURCE}, cfg, render=True)
            self.assertTrue(all(fields["replace_rules"] == "" for action, fields in Forms(empty).forms
                                if action == "/preview_paste"))

    def test_preview_logo_upload_and_retention_reject_unsafe_references(self):
        from PIL import Image
        from werkzeug.datastructures import FileStorage
        image = io.BytesIO()
        Image.new("RGB", (2, 2)).save(image, format="PNG")
        image.seek(0)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(dlms, "LOGO_TEMP_FOLDER", directory):
            upload = FileStorage(stream=image, filename="logo.png")
            name = dlms.save_preview_logo(dlms.app, upload)
            self.assertTrue(Path(directory, name).is_file())
            self.assertEqual(name, dlms.save_preview_logo(dlms.app, None, temp_logo_name=name))
            for bad in ("../temp_123.png", "/tmp/temp_123.png", "None", "temp_999.png"):
                self.assertIsNone(dlms.save_preview_logo(dlms.app, None, temp_logo_name=bad))

    def test_preview_explains_scope_and_escapes_source(self):
        body = self.preview({"quiz_text": SOURCE+'\n<script id="source-marker">bad()</script>'}, render=True)
        self.assertNotIn('<script id="source-marker">', body)
        self.assertIn("&lt;script", body)
        self.assertIn("not parsed questions", body)
        self.assertIn("do not verify facts or correct answers", body)
        self.assertNotIn("You can safely continue", body)
        self.assertNotIn("Formatting Looks Excellent", body)
