import glob
import os
import re
import unittest
from pathlib import Path

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from dlms.routes import help as help_routes


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
        self.assertEqual({key: help_routes.HELP_TOPIC_FILES[key] for key in expected}, expected)

        for topic, filename in help_routes.HELP_TOPIC_FILES.items():
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
        self.assertIn(f"DLMS {dlms.APP_VERSION} DOCUMENTATION", index)
        self.assertNotRegex(index, r"(?i)\brc[._ -]?4\b")
        self.assertIn("Learning Intelligence", index)
        self.assertIn("Anki &amp; Printable Cards", index)
        self.assertIn("System Tools &amp; Data Management", index)

    def test_every_registered_help_topic_is_in_the_index_and_shared_navigation(self):
        index = self._static("help.html")
        navigation = self._static("help-navigation.js")
        for topic in help_routes.HELP_TOPIC_FILES:
            with self.subTest(topic=topic, surface="index"):
                self.assertIn(f'href="/help/{topic}"', index)
            with self.subTest(topic=topic, surface="shared-navigation"):
                self.assertIn(f"['{topic}',", navigation)

    def test_build_quiz_help_links_external_ai_and_quiz_paste_uses_canonical_regex_route(self):
        build_quiz = self._static("help-build-quiz.html")
        self.assertIn('href="/help/external-ai"', build_quiz)
        self.assertIn("External AI Quiz Builder", build_quiz)
        self.assertIn("Import PDF &amp; image study content", build_quiz)
        self.assertIn("PDF question banks, terminology lists, scans, or screenshots", build_quiz)

        paste_template = Path(dlms.TEMPLATE_ROOT, "quiz", "paste.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('href="/regex-help"', paste_template)
        self.assertNotIn('href="/static/regex-help.html"', paste_template)

    def test_legacy_help_targets_remain_available(self):
        version_text = f"Documentation for DLMS {dlms.APP_VERSION}."
        for path in ("/help/quiz-help", "/help/advanced-features"):
            with self.subTest(path=path):
                response = self.client.get(path)
                try:
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(version_text, response.get_data(as_text=True))
                finally:
                    response.close()

        about = self._static("about.html")
        self.assertIn(f"DLMS {dlms.APP_VERSION} is a local training", about)
        self.assertIn(version_text, about)
        self.assertNotRegex(about, r"(?i)\brc[._ -]?4\b")

    def test_help_pages_use_current_version_and_shared_toc_script(self):
        help_files = glob.glob(os.path.join(dlms.STATIC_ROOT, "help*.html"))
        self.assertGreater(len(help_files), 1)
        version_text = f"Documentation for DLMS {dlms.APP_VERSION}."
        for path in help_files:
            with self.subTest(path=os.path.basename(path)):
                with open(path, encoding="utf-8") as handle:
                    page = handle.read()
                self.assertIn(version_text, page)
                self.assertNotRegex(page, r"Documentation for DLMS 3\.0\.[01]\.")
                self.assertIn('/static/help-docs.css', page)
                self.assertRegex(page, r'<body[^>]+class="[^"]*help-page[^"]*"')
                self.assertIn("/static/help-navigation.js", page)

        toc = self._static("help-navigation.js")
        self.assertIn("PDF & Image Import", toc)
        self.assertNotIn("'Smart PDF'", toc)
        self.assertIn("Learning Intelligence", toc)
        self.assertIn("Anki & Printable Cards", toc)
        self.assertIn("System Tools & Data Management", toc)

    def test_help_pages_do_not_use_retired_settings_section_names(self):
        retired_names = (
            "Data & History",
            "Data &amp; History",
            "Reset & Recovery",
            "Reset &amp; Recovery",
            "Maintenance & Recovery",
            "Maintenance &amp; Recovery",
        )
        help_files = glob.glob(os.path.join(dlms.STATIC_ROOT, "help*.html"))
        help_files.extend(
            os.path.join(dlms.STATIC_ROOT, filename)
            for filename in ("about.html", "quiz-help.html", "advanced-features.html")
        )
        for path in help_files:
            page = self._static(os.path.basename(path))
            for retired_name in retired_names:
                with self.subTest(page=os.path.basename(path), retired_name=retired_name):
                    self.assertNotIn(retired_name, page)

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
        self.assertIn("Anki Tools → Custom Deck &amp; Printable Cards", anki)

        maintenance = self._static("help-maintenance.html")
        self.assertIn("System Tools", maintenance)
        self.assertIn("not a routine update step", maintenance)
        self.assertIn("normally do not need to run it after updating DLMS", maintenance)
        self.assertIn("when DLMS specifically instructs you", maintenance)
        self.assertIn("look stale or inconsistent with the current quiz interface", maintenance)
        self.assertIn("generated HTML or playable JSON", maintenance)
        self.assertIn("derived HTML and playable JSON", maintenance)
        self.assertIn("concepts, Question Identity lineage, folders", maintenance)
        self.assertIn("source or provenance details", maintenance)
        self.assertIn("learning events", maintenance)
        self.assertIn("portable backup", maintenance)

    def test_pdf_and_image_import_is_the_user_facing_help_name(self):
        visible_help_files = glob.glob(os.path.join(dlms.STATIC_ROOT, "*.html"))
        for path in visible_help_files:
            with self.subTest(path=os.path.basename(path)):
                page = self._static(os.path.basename(path))
                self.assertNotIn("Smart PDF", page)

        topic = self._static("help-smart-pdf.html")
        self.assertIn("PDF &amp; Image Import", topic)
        self.assertIn('href="/help/smart-pdf"', topic)

    def test_pdf_and_image_help_distinguishes_screenshot_and_scanned_pdf_limits(self):
        topic = self._static("help-smart-pdf.html")
        self.assertIn("up to 25 screenshot images per batch", topic)
        self.assertIn("up to 25 selected scanned-PDF pages per import", topic)

    def test_data_safety_and_reset_help_matches_current_user_facing_contract(self):
        maintenance = self._static("help-maintenance.html")
        for section_id in ("tools", "backup-restore", "reset-remove"):
            with self.subTest(section=section_id):
                self.assertIn(f'id="{section_id}"', maintenance)

        for wording in (
            "Create &amp; Download Backup",
            "Recent safety backups",
            "Validate Backup &amp; Continue",
            "pre-restore safety backup",
            "attempts, their saved answers, and missed-question/history records",
            "quizzes themselves remain available",
            "Backup &amp; Restore",
            "Reset &amp; Remove",
            "Choose the narrowest reset",
            "Reset Quiz Library &amp; Results",
            "Clear Imported / Source Content",
            "Packs marked as protected are preserved",
            "Reset Application Settings",
            "application lifecycle, and Quiz Library folder preferences",
            "Quizzes keep their existing folder assignments",
            "empty configured folders are removed",
            "hidden-folder state is cleared",
            "Reset DLMS to Fresh State",
            "backup ZIPs in the DLMS backup folder are deliberately preserved",
            "Remove DLMS Data from This Computer",
            "REMOVE DLMS DATA",
            "executable or source installation itself is not removed",
        ):
            with self.subTest(wording=wording):
                self.assertIn(wording, maintenance)

        settings = self._static("help-settings.html")
        self.assertIn('/help/maintenance#backup-restore', settings)
        self.assertIn('/help/maintenance#reset-remove', settings)
        self.assertNotIn("Data &amp; History", settings)
        self.assertNotIn("Reset &amp; Recovery", settings)

    def test_help_distinguishes_library_reference_quiz_export_and_portable_backup(self):
        maintenance = self._static("help-maintenance.html")
        for wording in (
            "Download Quiz Library Reference (TXT)",
            "human-readable reference",
            "not a restorable or importable library package",
            "classic choice-question text representation",
            "does not preserve matching, image, or hotspot interaction",
            "Quiz Bundles</strong> for rich quiz transfer",
            "migration to another DLMS installation or a full restore",
        ):
            with self.subTest(wording=wording):
                self.assertIn(wording, maintenance)

    def test_quiz_help_documents_current_folder_visibility_and_controls(self):
        quizzes = self._static("help-quizzes.html")
        self.assertIn('href="#library-folders"', quizzes)
        self.assertIn('id="library-folders"', quizzes)
        for wording in (
            "New Folder",
            "saves and displays custom folders immediately",
            "remains visible in the <strong>Visible</strong> and <strong>All</strong> views",
            "Hidden</strong> view shows a visible folder only when it contains an individually hidden quiz",
            "a hidden folder remains available there even when empty",
            "No quizzes in this view.",
            "remains available after refresh or restart",
            "Uncategorized",
            "stays hidden when empty",
            "cannot be hidden, renamed, or deleted",
            "without changing the individual visibility of any quiz",
            "shows every quiz inside a hidden folder",
            "Hidden folder",
            "Unhiding a folder restores only the quizzes that are not individually hidden",
            "choose <strong>Move</strong>",
            "select the destination folder, and choose <strong>Save</strong>",
            "Hidden folders remain available as destinations",
            "Drag a folder header to reorder",
            "Drag a quiz card to reorder it inside its current folder",
            "does not transfer quizzes between folders",
            "Search can reveal a matching quiz from a hidden folder",
            "clearing the search restores normal folder visibility and saved empty folders",
        ):
            with self.subTest(wording=wording):
                self.assertIn(wording, quizzes)

    def test_getting_started_and_troubleshooting_explain_dlms_lifecycle(self):
        getting_started = self._static("help-getting-started.html")
        troubleshooting = self._static("help-troubleshooting.html")

        self.assertIn('id="lifecycle"', getting_started)
        for wording in (
            "normal local desktop mode",
            "immediate and recommended way to stop the application",
            "closing the final DLMS browser window may trigger automatic shutdown",
            "in-app browser/API shutdown and automatic browser-presence shutdown are unavailable",
            "Closing client browser windows does not stop the server",
            "Stop the DLMS process or service from the host computer",
            "http://127.0.0.1:9001/",
            "instead of starting another server copy",
            "<strong>Shutdown DLMS</strong>",
            "Windows, macOS, and Linux",
        ):
            with self.subTest(page="getting-started", wording=wording):
                self.assertIn(wording, getting_started)

        self.assertIn('id="browser-closed"', troubleshooting)
        for wording in (
            "normal local desktop mode",
            "immediate, recommended way to stop the application",
            "closing the final DLMS browser window may stop the process automatically",
            "in-app browser/API shutdown and automatic browser-presence shutdown are unavailable",
            "Closing client browser windows does not stop the server",
            "Stop the DLMS process or service from the host computer",
            "already-running DLMS process",
            "<strong>Shutdown DLMS</strong>",
            "If the address no longer responds",
        ):
            with self.subTest(page="troubleshooting", wording=wording):
                self.assertIn(wording, troubleshooting)

    def test_help_makes_todays_review_the_default_and_distinguishes_review_options(self):
        getting_started = self._static("help-getting-started.html")
        learning = self._static("help-learning-intelligence.html")

        self.assertIn("What should I study right now?", getting_started)
        self.assertIn("Start with <strong>Today’s Review</strong>", getting_started)
        self.assertIn('id="which-review"', learning)
        for wording in (
            "Recommended starting point:",
            "Today’s Review",
            "Adaptive Study",
            "Smart Review",
            "Concept Review",
            "Due Questions",
            "Topic Retention Schedule",
            "Missed-question review",
        ):
            with self.subTest(wording=wording):
                self.assertIn(wording, learning)
        self.assertNotIn("available confidence", learning)
        for wording in (
            "weak or developing concepts",
            "recent misses",
            "low recent accuracy",
            "review timing",
            "material not studied recently",
            "repeated exposure",
        ):
            with self.subTest(adaptive_signal=wording):
                self.assertIn(wording, learning)
        for wording in (
            "total number currently due",
            "includes up to 20 questions",
            "10, 20, 30, or 50 questions",
            "recalculates the remaining due count",
        ):
            with self.subTest(due_batch_wording=wording):
                self.assertIn(wording, learning)

    def test_help_explains_cross_quiz_evidence_trends_and_identity_in_plain_language(self):
        learning = self._static("help-learning-intelligence.html")
        for wording in (
            "how many source questions and quizzes cover each concept",
            "overall accuracy",
            "Recent accuracy",
            "up to the five latest deduplicated answers",
            "at least six answers",
            "Not enough data",
            "durable link to its original source question",
            "Independently authored questions with identical wording remain separate",
            "conservative compatibility fallback",
        ):
            with self.subTest(wording=wording):
                self.assertIn(wording, learning)

    def test_help_documents_current_library_tools_and_dynamic_views(self):
        quizzes = self._static("help-quizzes.html")
        self.assertIn('id="library-views"', quizzes)
        self.assertIn('id="library-tools"', quizzes)
        for wording in (
            "Needs Review",
            "Recently Added",
            "Low Score",
            "Unfinished",
            "OCR Imported",
            "Mix Questions",
            "Find Duplicates",
            "Quiz Bundles",
            "advisory only",
            "Learning history and review schedules are excluded",
        ):
            with self.subTest(wording=wording):
                self.assertIn(wording, quizzes)

    def test_help_documents_external_ai_and_local_ocr_matching(self):
        external_ai = self._static("help-external-ai.html")
        pdf_image = self._static("help-smart-pdf.html")
        for wording in (
            "Choice questions",
            "Matching / terminology",
            "2–100 complete, distinct term/definition pairs",
            "confirm every final pairing",
            "downloadable DLMS Study Pack ZIP",
        ):
            with self.subTest(surface="external-ai", wording=wording):
                self.assertIn(wording, external_ai)
        for wording in (
            "Terminology and matching OCR",
            "up to 25 ordered",
            "Term — Definition",
            "Term: Definition",
            "two-column lists",
            "unassigned material",
            "Once extraction becomes a matching Review &amp; Repair draft",
            "removes the temporary uploaded images or rendered PDF pages",
            "source names, diagnostics, and unassigned text",
            "Keep your original source files available while reviewing",
        ):
            with self.subTest(surface="ocr", wording=wording):
                self.assertIn(wording, pdf_image)
        self.assertNotIn(
            "Scanned-page OCR currently applies to question-bank imports, not glossary extraction",
            pdf_image,
        )
        self.assertNotIn(
            "temporary sources are removed after publication, cancellation, or expiration",
            pdf_image,
        )

    def test_help_distinguishes_study_packs_from_content_pack_management(self):
        study = self._static("help-study-packs.html")
        content = self._static("help-content-management.html")
        self.assertIn("Study Packs</strong> is the learner-facing catalog", study)
        self.assertIn("Content Packs</strong> is the management workspace", study)
        self.assertIn("Two views of the same installed material", content)

    def test_user_facing_learning_surfaces_do_not_show_internal_roadmap_ids(self):
        surfaces = (
            Path(dlms.TEMPLATE_ROOT, "dashboard", "index.html"),
            Path(dlms.STATIC_ROOT, "learning-intelligence.html"),
            Path(dlms.STATIC_ROOT, "learning-profile.html"),
            Path(dlms.STATIC_ROOT, "learning-diagnostics.html"),
            Path(dlms.STATIC_ROOT, "review-schedule.html"),
        )
        roadmap_id = re.compile(r"DLMS-\d{3}(?:/\d{3})?")
        for path in surfaces:
            with self.subTest(filename=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), roadmap_id)

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
                ("backup-restore", "settings-backup_restore.webp"),
                ("reset-remove", "settings-reset_remove.webp"),
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
                        self.assertIn(topic, help_routes.HELP_TOPIC_FILES)

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
