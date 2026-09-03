import os
import re
import unittest
from unittest import mock

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms


class NavigationLayoutTests(unittest.TestCase):
    @staticmethod
    def _static(name):
        with open(os.path.join(dlms.STATIC_ROOT, name), encoding="utf-8") as handle:
            return handle.read()

    def setUp(self):
        self.client = dlms.app.test_client()

    def test_dashboard_renders_full_release_candidate_version(self):
        response = self.client.get("/")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(page.count(f"DLMS v{dlms.APP_VERSION}"), 2)
        self.assertNotRegex(page, r"DLMS v3\.0\.2(?! RC4)")

    def test_settings_hub_uses_standard_shell_without_migration_copy(self):
        response = self.client.get("/settings")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('class="dashboard-shell"', page)
        self.assertIn('id="dashboardSidebar"', page)
        self.assertIn('data-settings-menu', page)
        self.assertIn("System Tools", page)
        self.assertIn('href="/settings/backup"', page)
        self.assertIn("Backup &amp; Restore", page)
        self.assertIn('href="/settings/reset-remove"', page)
        self.assertIn("Reset &amp; Remove", page)
        self.assertNotIn("Data &amp; History", page)
        self.assertNotIn("Reset &amp; Recovery", page)
        self.assertNotIn("← Dashboard", page)
        self.assertNotIn("Settings migration complete", page)
        self.assertNotIn("settings-migration-note", self._static("style.css"))

    def test_settings_category_pages_use_standard_shell(self):
        for path in ("/settings/appearance", "/settings/ai", "/settings/parsing", "/settings/backup", "/settings/reset-remove"):
            with self.subTest(path=path):
                response = self.client.get(path)
                page = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertIn('class="dashboard-shell"', page)
                self.assertIn('id="dashboardSidebar"', page)
                self.assertIn('data-settings-menu', page)
                self.assertIn("/settings", page)

    def test_settings_data_destinations_and_history_clear_location_match_current_ia(self):
        backup = self.client.get("/settings/backup").get_data(as_text=True)
        reset = self.client.get("/settings/reset-remove").get_data(as_text=True)

        self.assertIn("SETTINGS / BACKUP &amp; RESTORE", backup)
        self.assertIn("/settings/backup/create", backup)
        self.assertIn("/settings/backup/restore/stage", backup)
        self.assertNotIn("Persistent Exam Result Storage", backup)
        self.assertNotIn("clearDBBtn", backup)

        self.assertIn("SETTINGS / RESET &amp; REMOVE", reset)
        self.assertIn("Persistent Exam Result Storage", reset)
        self.assertIn('id="clearDBBtn"', reset)
        self.assertIn('/api/clear_db_history', reset)
        self.assertIn('location.href=\'/settings/backup\'', reset)

    def test_legacy_settings_data_destinations_redirect_to_current_pages(self):
        data = self.client.get("/settings/data")
        reset = self.client.get("/settings/reset")

        self.assertEqual(data.status_code, 302)
        self.assertTrue(data.headers["Location"].endswith("/settings/backup"))
        self.assertEqual(reset.status_code, 302)
        self.assertTrue(reset.headers["Location"].endswith("/settings/reset-remove"))

    def test_legacy_settings_route_redirects_to_appearance(self):
        response = self.client.get("/settings/legacy")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/settings/appearance"))

    def test_system_tools_uses_standard_shell_and_keeps_rebuild_action(self):
        response = self.client.get("/admin/maintenance")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('class="dashboard-shell"', page)
        self.assertIn("SETTINGS / SYSTEM TOOLS", page)
        self.assertIn("Rebuild All Quiz Pages", page)
        self.assertIn("Open Image Study Editor", page)
        self.assertNotIn("Back To Dashboard", page)

    def test_normalized_navigation_owns_system_tools_routing(self):
        source = self._static("nav-normalize.js")

        self.assertIn("path === '/admin/maintenance'", source)
        self.assertIn("item('settings','/settings','⚙','Settings')", source)
        self.assertIn("item('image','/admin/image-editor','◎','Image Study Editor')", source)
        self.assertNotIn("item('maintenance','/admin/maintenance'", source)

    def test_sidebar_scanability_keeps_ordered_destinations_and_marks_nested_context(self):
        source = self._static("nav-normalize.js")
        css = self._static("style.css")
        learning_page = self._static("learning-intelligence.html")

        self.assertIn("primarySection('Study')", source)
        self.assertIn("primarySection('Progress & tools')", source)
        self.assertLess(source.index("primarySection('Study')"), source.index("item('study'"))
        self.assertLess(source.index("primarySection('Progress & tools')"), source.index("item('history'"))
        self.assertIn("const isActiveParent", source)
        self.assertIn("const current = active && !isActiveParent(key)", source)
        self.assertIn("const context = active && isActiveParent(key)", source)
        self.assertIn("key === 'anki' && ankiOpen && path !== '/anki'", source)
        self.assertIn("dashboard-nav-primary-section-label", css)
        self.assertIn("dashboard-nav-item.nav-context", css)
        self.assertNotIn("dashboard-nav-subitem.active::before", css)
        self.assertIn("var(--theme-accent", css)
        for page in ("learning-intelligence.html", "learning-profile.html", "review-schedule.html", "learning-diagnostics.html"):
            with self.subTest(page=page):
                self.assertIn('data-navigation-seed="canonical"', self._static(page))
        self.assertIn('class="dashboard-nav-item active nav-context" data-nav-key="learning"', learning_page)
        self.assertIn('class="dashboard-nav-subitem active" href="/learning-intelligence" aria-current="page"', learning_page)

    def test_learning_intelligence_expansion_model_keeps_the_current_section_open_without_reloading_its_landing_page(self):
        source = self._static("nav-normalize.js")

        self.assertIn("const learningOpen = isActive('learning')", source)
        self.assertIn("path !== '/anki'", source)
        self.assertIn('data-navigation-seed="canonical"', self._static("learning-intelligence.html"))
        self.assertIn("const canonicalSeed = sidebar.querySelector", source)
        self.assertIn("if (canonicalSeed)", source)
        self.assertIn("path !== '/learning-intelligence'", source)
        self.assertIn("event.preventDefault()", source)

    def test_learning_intelligence_seed_pages_have_one_current_child_and_a_context_only_parent(self):
        expected_child_pages = {
            "learning-intelligence.html": "/learning-intelligence",
            "learning-profile.html": "/learning-profile",
            "review-schedule.html": "/review-schedule",
            "learning-diagnostics.html": "/learning-diagnostics",
        }

        for filename, current_href in expected_child_pages.items():
            with self.subTest(filename=filename):
                page = self._static(filename)
                self.assertIn('class="dashboard-nav-item active nav-context" data-nav-key="learning"', page)
                self.assertNotIn('data-nav-key="learning" href="/learning-intelligence" aria-current="page"', page)
                self.assertEqual(1, page.count('aria-current="page"'))
                self.assertIn(
                    f'class="dashboard-nav-subitem active" href="{current_href}" aria-current="page"',
                    page,
                )

    def test_navigation_configuration_reconciles_visibility_without_a_second_mount(self):
        source = self._static("nav-normalize.js")

        self.assertIn("const studyAreaVisibilityCacheKey = 'dlms.studyAreaVisibility.v1'", source)
        self.assertIn("const initialStudyAreaVisibility = readCachedStudyAreaVisibility()", source)
        self.assertIn("data-nav-key=\"${key}\"", source)
        self.assertIn("if (navItem) navItem.hidden = !visible", source)
        self.assertIn("form[action=\"/settings/navigation/save\"]", source)

        configuration_sync = source[source.index("fetch('/config/portal.json'"):source.index("themeSelect.addEventListener('change'")]
        self.assertIn("applyStudyAreaVisibility(visibility)", configuration_sync)
        self.assertIn("cacheStudyAreaVisibility(visibility)", configuration_sync)
        self.assertNotIn("mountNavigation(", configuration_sync)

    def test_image_editor_context_link_uses_system_tools(self):
        self.assertIn("← System Tools", dlms.HOTSPOT_EDITOR_TEMPLATE)
        self.assertNotIn("← Back to Maintenance", dlms.HOTSPOT_EDITOR_TEMPLATE)

    def test_medical_empty_state_uses_dedicated_semantic_spacing_rules(self):
        with mock.patch.object(dlms, "_medical_pack_page_data", return_value=(None, [], [])):
            page = self.client.get("/medical").get_data(as_text=True)
        css = self._static("style.css")

        self.assertIn("medical-empty-state-panel", page)
        self.assertIn(".medical-study-page .medical-empty-state-panel", css)
        self.assertIn("padding: var(--dlms-space-xl)", css)
        self.assertIn("padding: var(--dlms-space-lg)", css)
        self.assertIn("grid-template-columns: max-content minmax(0, 1fr)", css)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn("var(--theme-muted-text", css)

    def test_it_summary_supporting_text_uses_full_card_width_and_normal_words(self):
        pack = {"name": "IT Study", "version": "1"}
        with mock.patch.object(dlms, "_it_pack_page_data", return_value=(pack, [], [], [])):
            page = self.client.get("/it").get_data(as_text=True)
        css = self._static("style.css")

        self.assertIn("IT / Cybersecurity packs", page)
        rule = re.search(
            r"\.medical-summary-grid\s+\.dashboard-stat-card\s*\{([^}]*)\}", css
        )
        self.assertIsNotNone(rule)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", rule.group(1))
        support_rules = re.findall(
            r"\.medical-summary-grid\s+\.dashboard-stat-card\s*>\s*small\s*\{([^}]*)\}",
            css,
        )
        self.assertTrue(support_rules)
        self.assertTrue(any("overflow-wrap: break-word" in rule for rule in support_rules))
        self.assertTrue(any("word-break: normal" in rule for rule in support_rules))
        self.assertFalse(any("overflow-wrap: anywhere" in rule for rule in support_rules))

    def test_learning_intelligence_modal_is_viewport_safe_and_focus_managed(self):
        page = self._static("learning-intelligence.html")
        css = self._static("style.css")

        self.assertIn("learning-intelligence-model-close", page)
        self.assertNotIn('class="help-lightbox-close" data-li-model-close', page)
        self.assertIn("previousModalFocus", page)
        self.assertIn("requestAnimationFrame(()=>modalCloseButton.focus())", page)
        self.assertIn("focusTarget?.focus?.()", page)
        self.assertIn("if(e.key!=='Tab')return", page)
        self.assertIn("data-li-model-close", page)
        self.assertIn("max-height: calc(100dvh - 24px)", css)
        self.assertIn(".learning-intelligence-model-dialog", css)
        self.assertIn("overflow: auto", css)
        self.assertIn(".learning-intelligence-model-close", css)

    def test_learning_intelligence_summary_uses_full_width_text_rows(self):
        page = self._static("learning-intelligence.html")
        css = self._static("style.css")

        card = re.search(
            r"\.learning-intelligence-summary\s+\.dashboard-stat-card\s*\{([^}]*)\}",
            css,
        )
        self.assertIsNotNone(card)
        self.assertIn("grid-template-columns:minmax(0,1fr)", card.group(1))
        self.assertIn("min-height:124px", card.group(1))

        text_rows = re.search(
            r"\.learning-intelligence-summary\s+\.dashboard-stat-card>span,\s*"
            r"\.learning-intelligence-summary\s+\.dashboard-stat-card>strong,\s*"
            r"\.learning-intelligence-summary\s+\.dashboard-stat-card>small\s*\{([^}]*)\}",
            css,
        )
        self.assertIsNotNone(text_rows)
        self.assertIn("width:100%", text_rows.group(1))
        self.assertIn("overflow-wrap:break-word", text_rows.group(1))
        self.assertIn("word-break:normal", text_rows.group(1))

        self.assertRegex(
            css,
            r"@media\(max-width:1100px\)\s*\{\s*\.learning-intelligence-summary"
            r"\s*\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)",
        )
        self.assertRegex(
            css,
            r"@media\(max-width:560px\)\s*\{\.learning-intelligence-summary"
            r"\{grid-template-columns:1fr;\}",
        )

        action = re.search(
            r"\.learning-intelligence-page\s+\.build-secondary-link\s*\{([^}]*)\}",
            css,
        )
        self.assertIsNotNone(action)
        self.assertIn("flex:0 0 auto", action.group(1))
        self.assertIn("max-width:100%", action.group(1))
        self.assertIn("white-space:normal", action.group(1))
        self.assertEqual(page.count('class="build-secondary-link"'), 3)
        self.assertIn('class="build-secondary-link" id="liModelButton"', page)
        self.assertIn('class="build-secondary-link" id="liToggleZeroEvidence"', page)


if __name__ == "__main__":
    unittest.main()
