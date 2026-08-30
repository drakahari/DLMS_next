import glob
import os
import re
import unittest

import app as dlms


class HelpDocumentationTests(unittest.TestCase):
    @staticmethod
    def _static(name):
        with open(os.path.join(dlms.STATIC_ROOT, name), encoding="utf-8") as handle:
            return handle.read()

    def setUp(self):
        self.client = dlms.app.test_client()

    def test_help_topic_map_serves_the_current_task_oriented_topics(self):
        expected = {
            "getting-started": "help-getting-started.html",
            "study-packs": "help-study-packs.html",
            "study-modules": "help-study-modules.html",
            "history-analytics": "help-history-analytics.html",
            "learning-intelligence": "help-learning-intelligence.html",
            "anki": "help-anki.html",
            "settings": "help-settings.html",
            "maintenance": "help-maintenance.html",
        }
        self.assertEqual({key: dlms.HELP_TOPIC_FILES[key] for key in expected}, expected)

        for topic, filename in dlms.HELP_TOPIC_FILES.items():
            with self.subTest(topic=topic):
                self.assertTrue(os.path.isfile(os.path.join(dlms.STATIC_ROOT, filename)))
                response = self.client.get(f"/help/{topic}")
                try:
                    self.assertEqual(response.status_code, 200)
                finally:
                    response.close()

        response = self.client.get("/help/")
        try:
            index = response.get_data(as_text=True)
        finally:
            response.close()
        self.assertIn("Learning Intelligence", index)
        self.assertIn("Anki &amp; Printable Cards", index)
        self.assertIn("System Tools &amp; Recovery", index)

    def test_legacy_help_targets_remain_available(self):
        for path in ("/help/quiz-help", "/help/advanced-features"):
            with self.subTest(path=path):
                response = self.client.get(path)
                try:
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("Documentation for DLMS 3.0.2.", response.get_data(as_text=True))
                finally:
                    response.close()

        self.assertIn("Documentation for DLMS 3.0.2.", self._static("about.html"))

    def test_help_pages_use_current_version_and_shared_toc_script(self):
        help_files = glob.glob(os.path.join(dlms.STATIC_ROOT, "help*.html"))
        self.assertGreater(len(help_files), 1)
        for path in help_files:
            with self.subTest(path=os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    page = handle.read()
                self.assertIn("Documentation for DLMS 3.0.2.", page)
                self.assertNotRegex(page, r"Documentation for DLMS 3\.0\.[01]\.")
                self.assertIn('/static/help-docs.css', page)
                self.assertRegex(page, r'<body[^>]+class="[^"]*help-page[^"]*"')
                self.assertIn("/static/help-navigation.js", page)

        toc = self._static("help-navigation.js")
        self.assertIn("Learning Intelligence", toc)
        self.assertIn("Anki & Printable Cards", toc)
        self.assertIn("System Tools & Recovery", toc)

    def test_study_pack_help_documents_current_guided_zip_and_mcq_workflow(self):
        page = self._static("help-study-packs.html")
        for wording in (
            "Configure.",
            "Generate Prompt.",
            "Bring Back ZIP.",
            "Validate.",
            "Install.",
            "Study.",
            "Multiple-Choice Questions",
            "single-select",
            "one choice is marked correct",
            "should not guess a correct answer",
            "invent a citation",
            "Plain pasted AI prose is not installable",
        ):
            with self.subTest(wording=wording):
                self.assertIn(wording, page)

    def test_law_settings_printable_and_system_tools_guidance_is_current(self):
        law = self._static("help-study-modules.html")
        self.assertIn("Save &amp; Preview Case Packet", law)
        self.assertIn("Create Case Review From Import", law)
        self.assertIn("opens the exact saved Case Review", law)

        settings = self._static("help-settings.html")
        for wording in ("Settings → Navigation", "Dark", "Light", "Purple &amp; Gold", "Maroon &amp; Gold", "System Tools"):
            with self.subTest(setting=wording):
                self.assertIn(wording, settings)

        anki = self._static("help-anki.html")
        for wording in ("Printable", "Avery 5388", "long-edge", "short-edge", "duplex"):
            with self.subTest(printable=wording):
                self.assertIn(wording, anki)

        maintenance = self._static("help-maintenance.html")
        self.assertIn("System Tools", maintenance)
        self.assertIn("portable backup", maintenance)

    def test_help_asset_references_exist(self):
        asset_reference = re.compile(r'''(?:src|href)=["'](/static/help_assets/[^"']+)["']''')
        for path in glob.glob(os.path.join(dlms.STATIC_ROOT, "help*.html")):
            with open(path, encoding="utf-8") as handle:
                for asset in asset_reference.findall(handle.read()):
                    with self.subTest(page=os.path.basename(path), asset=asset):
                        local_path = os.path.join(dlms.STATIC_ROOT, asset.removeprefix("/static/"))
                        self.assertTrue(os.path.isfile(local_path), local_path)

    def test_visual_guides_have_required_screenshots_alt_text_and_captions(self):
        expected_assets = {
            "help-learning-intelligence.html": (
                ("mastery", "learning-topics.png"),
                ("reviews", "learning-review-schedule.png"),
                ("diagnostics", "learning-diagnostics-confusions.png"),
                ("diagnostics", "learning-question-quality.png"),
            ),
            "help-study-packs.html": (("ai-workflow", "ai-builder-zip-return.png"), ("ai-workflow", "study-pack-validation.png")),
            "help-anki.html": (("printable", "anki-print-controls.png"), ("printable", "anki-print-front.png"), ("printable", "anki-print-back.png")),
            "help-study-modules.html": (("law", "law-create-case.png"), ("law", "law-import-packet.png")),
            "help-settings.html": (("navigation", "settings-navigation.png"),),
            "help-maintenance.html": (("tools", "system-tools.png"),),
        }
        for filename, placements in expected_assets.items():
            page = self._static(filename)
            for section_id, asset in placements:
                with self.subTest(page=filename, section=section_id, asset=asset):
                    start = page.index(f'id="{section_id}"')
                    end = page.find('<section ', start + 1)
                    section = page[start:] if end < 0 else page[start:end]
                    self.assertIn(f'/static/help_assets/{asset}', page)
                    self.assertIn(f'/static/help_assets/{asset}', section)
                    self.assertRegex(section, rf'<img[^>]+src="/static/help_assets/{re.escape(asset)}"[^>]+alt="[^"]+"')
                    self.assertRegex(section, rf'<img[^>]+src="/static/help_assets/{re.escape(asset)}"[^>]+class="help-screenshot-052b"[^>]+loading="eager"[^>]*></a><figcaption>[^<]+</figcaption>')
                    response = self.client.get(f'/static/help_assets/{asset}')
                    try:
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.mimetype, 'image/png')
                    finally:
                        response.close()

    def test_help_topic_links_target_registered_topics(self):
        topic_reference = re.compile(r'''href=["']/help/([^"'#?]+)''')
        pages = glob.glob(os.path.join(dlms.STATIC_ROOT, "help*.html"))
        pages.extend(
            os.path.join(dlms.STATIC_ROOT, filename)
            for filename in ("about.html", "quiz-help.html", "advanced-features.html")
        )
        for path in pages:
            with open(path, encoding="utf-8") as handle:
                for topic in topic_reference.findall(handle.read()):
                    with self.subTest(page=os.path.basename(path), topic=topic):
                        self.assertIn(topic, dlms.HELP_TOPIC_FILES)

    def test_getting_started_includes_short_trusted_lan_guidance(self):
        page = self._static("help-getting-started.html")
        self.assertIn("trusted LAN", page)
        self.assertIn("public internet", page)


if __name__ == "__main__":
    unittest.main()
