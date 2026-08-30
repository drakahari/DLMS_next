import os
import unittest
from unittest import mock

import app as dlms


class NavigationLayoutTests(unittest.TestCase):
    @staticmethod
    def _static(name):
        with open(os.path.join(dlms.STATIC_ROOT, name), encoding="utf-8") as handle:
            return handle.read()

    def setUp(self):
        self.client = dlms.app.test_client()

    def test_settings_hub_uses_standard_shell_without_migration_copy(self):
        response = self.client.get("/settings")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('class="dashboard-shell"', page)
        self.assertIn('id="dashboardSidebar"', page)
        self.assertIn('data-settings-menu', page)
        self.assertIn("System Tools", page)
        self.assertNotIn("← Dashboard", page)
        self.assertNotIn("Settings migration complete", page)
        self.assertNotIn("settings-migration-note", self._static("style.css"))

    def test_settings_category_pages_use_standard_shell(self):
        for path in ("/settings/appearance", "/settings/ai", "/settings/parsing", "/settings/data", "/settings/reset"):
            with self.subTest(path=path):
                response = self.client.get(path)
                page = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertIn('class="dashboard-shell"', page)
                self.assertIn('id="dashboardSidebar"', page)
                self.assertIn('data-settings-menu', page)
                self.assertIn("/settings", page)

    def test_legacy_settings_route_remains_available(self):
        response = self.client.get("/settings/legacy")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Dashboard Configuration", page)
        self.assertNotIn('class="dashboard-shell"', page)

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


if __name__ == "__main__":
    unittest.main()
