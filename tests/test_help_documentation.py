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
        for wording in ("Printable", "Avery 5388", "long-edge", "short-edge", "duplex", "Missed Questions", "DLMS-exported multiple-choice card"):
            with self.subTest(printable=wording):
                self.assertIn(wording, anki)

        maintenance = self._static("help-maintenance.html")
        self.assertIn("System Tools", maintenance)
        self.assertIn("portable backup", maintenance)

    def test_data_safety_and_reset_help_matches_current_user_facing_contract(self):
        maintenance = self._static("help-maintenance.html")
        for section_id in ("tools", "data-safety", "reset-recovery"):
            with self.subTest(section=section_id):
                self.assertIn(f'id="{section_id}"', maintenance)

        for wording in (
            "Create &amp; Download Backup",
            "Recent safety backups",
            "Validate Backup &amp; Continue",
            "pre-restore safety backup",
            "attempts, their saved answers, and missed-question/history records",
            "quizzes themselves remain available",
            "Choose the narrowest reset",
            "Reset Quiz Library &amp; Results",
            "Clear Imported / Source Content",
            "Packs marked as protected are preserved",
            "Reset Application Settings",
            "Reset DLMS to Fresh State",
            "backup ZIPs in the DLMS backup folder are deliberately preserved",
            "Remove DLMS Data from This Computer",
            "REMOVE DLMS DATA",
            "executable or source installation itself is not removed",
        ):
            with self.subTest(wording=wording):
                self.assertIn(wording, maintenance)

        settings = self._static("help-settings.html")
        self.assertIn('/help/maintenance#data-safety', settings)
        self.assertIn('/help/maintenance#reset-recovery', settings)

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
                ("mastery", "learning-topics.webp"),
                ("reviews", "learning-review-schedule.webp"),
                ("diagnostics", "learning-diagnostics-confusions.webp"),
                ("diagnostics", "learning-question-quality.webp"),
            ),
            "help-study-packs.html": (("ai-workflow", "ai-builder-zip-return.webp"), ("ai-workflow", "study-pack-validation.webp")),
            "help-anki.html": (("anki", "anki-imported-card.png"), ("printable", "anki-print-controls.webp"), ("printable", "anki-print-front.webp"), ("printable", "anki-print-back.webp")),
            "help-study-modules.html": (("law", "law-create-case.webp"), ("law", "law-import-packet.webp")),
            "help-settings.html": (("navigation", "settings-navigation.webp"),),
            "help-maintenance.html": (
                ("tools", "system-tools.webp"),
                ("data-safety", "settings-data_history.webp"),
                ("reset-recovery", "settings-reset_recovery.webp"),
            ),
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
                    self.assertRegex(section, rf'<img[^>]+src="/static/help_assets/{re.escape(asset)}"[^>]+alt="[^"]+"[^>]*></a><figcaption>[^<]+</figcaption>')
                    if asset.endswith(".png"):
                        self.assertRegex(section, rf'<img[^>]+src="/static/help_assets/{re.escape(asset)}"[^>]+class="help-screenshot-052b"[^>]+loading="eager"')
                    response = self.client.get(f'/static/help_assets/{asset}')
                    try:
                        self.assertEqual(response.status_code, 200)
                        expected_mimetype = 'image/png' if asset.endswith('.png') else 'image/webp'
                        self.assertEqual(response.mimetype, expected_mimetype)
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

    def test_numbered_procedures_keep_inline_emphasis_inside_normal_text_flow(self):
        affected_pages = (
            "help-study-packs.html",
            "help-study-modules.html",
            "help-content-management.html",
            "help-anki.html",
        )
        mixed_inline_step = re.compile(
            r'<div class="help-steps">.*?<div>[^<]*'
            r'<strong>[^<]+</strong>[^<]+',
            re.DOTALL,
        )
        for filename in affected_pages:
            with self.subTest(page=filename):
                page = self._static(filename)
                self.assertRegex(page, mixed_inline_step)

        css = self._static("help-docs.css")
        step_rule = re.search(r"\.help-steps\s*>\s*div\s*\{([^}]*)\}", css)
        self.assertIsNotNone(step_rule)
        declarations = step_rule.group(1)
        self.assertIn("display: block", declarations)
        self.assertIn("min-width: 0", declarations)
        self.assertIn("white-space: normal", declarations)
        self.assertIn("overflow-wrap: break-word", declarations)
        self.assertIn("word-break: normal", declarations)
        self.assertNotIn("grid-template-columns", declarations)


if __name__ == "__main__":
    unittest.main()
