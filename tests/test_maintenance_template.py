"""Characterization coverage for the System Tools maintenance view."""

import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import maintenance as maintenance_routes
from tests.csrf_test_utils import csrf_headers, csrf_token


class MaintenanceTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    def _page(self):
        response = self.client.get("/admin/maintenance")
        self.assertEqual(200, response.status_code)
        return response.get_data(as_text=True)

    def test_route_uses_external_template_without_context(self):
        with mock.patch.object(
            maintenance_routes,
            "render_template",
            wraps=maintenance_routes.render_template,
        ) as render_template:
            response = self.client.get("/admin/maintenance")

        self.assertEqual(200, response.status_code)
        render_template.assert_called_once_with("admin/maintenance.html")
        self.assertTrue(
            (Path(dlms.TEMPLATE_ROOT) / "admin" / "maintenance.html").is_file()
        )

    def test_get_preserves_rendering_navigation_and_accessibility(self):
        page = self._page()

        self.assertIn("<title>System Tools - DLMS</title>", page)
        self.assertIn('class="dashboard-home system-tools-page"', page)
        self.assertIn('class="dashboard-shell"', page)
        self.assertIn('id="dashboardSidebar"', page)
        self.assertIn("SETTINGS / SYSTEM TOOLS", page)
        self.assertIn("Rebuild All Quiz Pages", page)
        self.assertIn(
            "It does not recreate quiz JSON, change questions or answers, change quiz IDs or registry entries, or rewrite attempt history.",
            page,
        )
        self.assertIn('href="/admin/image-editor"', page)
        self.assertIn("Open Image Study Editor", page)
        self.assertIn(
            'id="rebuildAllBtn" class="build-primary-button" type="button"', page
        )
        self.assertIn(
            'id="rebuildStatus" class="system-tools-status" aria-live="polite"',
            page,
        )
        self.assertNotIn("<form", page)
        self.assertIn('aria-label="Toggle navigation"', page)
        self.assertIn('aria-controls="dashboardSidebar"', page)
        self.assertIn('aria-expanded="false"', page)
        self.assertIn('<script src="/static/nav-normalize.js"></script>', page)

    def test_rebuild_javascript_confirmation_request_and_states_are_unchanged(self):
        page = self._page()

        self.assertIn(
            "Rebuild all quiz pages using the current DLMS template?\\n\\n", page
        )
        self.assertIn(
            "Quiz questions, answers, IDs, and history will not be changed.", page
        )
        self.assertIn("if (!ok) return;", page)
        self.assertIn("rebuildBtn.disabled = true;", page)
        self.assertIn(
            'rebuildStatus.textContent = "Rebuilding quiz pages...";', page
        )
        self.assertIn(
            'fetch("/admin/rebuild_all_quiz_html", {method: "POST"})', page
        )
        self.assertIn('throw new Error("Rebuild request failed")', page)
        self.assertIn(
            "`Complete: ${data.rebuilt} rebuilt, ${data.failed.length} failed.`",
            page,
        )
        self.assertIn(
            'rebuildStatus.textContent = "Rebuild failed. Check the server log.";',
            page,
        )
        self.assertIn("rebuildBtn.disabled = false;", page)

    def test_inline_javascript_has_no_jinja_values_and_uses_text_only_status(self):
        page = self._page()
        inline_script = page.split("<script>", 1)[1].split("</script>", 1)[0]

        self.assertNotIn("{{", inline_script)
        self.assertNotIn("{%", inline_script)
        self.assertIn("rebuildStatus.textContent =", inline_script)
        self.assertNotIn("rebuildStatus.innerHTML", inline_script)

    def test_rebuild_endpoint_preserves_id_coercion_skip_and_failure_reporting(self):
        registry = [
            {"id": None},
            {"id": "7"},
            {"id": 8},
            {"id": "not-an-id"},
            {"id": 9},
        ]

        def rebuild(quiz_id):
            if quiz_id == 7:
                return True
            if quiz_id == 8:
                return False
            raise RuntimeError("characterized rebuild failure")

        with mock.patch.object(dlms, "load_registry", return_value=registry), \
             mock.patch.object(
                 dlms, "rebuild_quiz_html_from_registry", side_effect=rebuild
             ) as rebuild_call:
            response = self.client.post(
                "/admin/rebuild_all_quiz_html",
                headers=csrf_headers(self.client, "/admin/maintenance"),
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"status": "complete", "rebuilt": 1, "failed": [8, "not-an-id", 9]},
            response.get_json(),
        )
        self.assertEqual(
            [mock.call(7), mock.call(8), mock.call(9)], rebuild_call.call_args_list
        )

    def test_rebuild_is_post_only_and_csrf_protected_before_registry_access(self):
        with mock.patch.object(dlms, "load_registry") as load_registry:
            get_response = self.client.get("/admin/rebuild_all_quiz_html")
            missing_token = self.client.post("/admin/rebuild_all_quiz_html")

        self.assertEqual(405, get_response.status_code)
        self.assertEqual(400, missing_token.status_code)
        load_registry.assert_not_called()

        token = csrf_token(self.client, "/admin/maintenance")
        with mock.patch.object(dlms, "load_registry") as load_registry:
            cross_origin = self.client.post(
                "/admin/rebuild_all_quiz_html",
                headers={
                    "X-CSRFToken": token,
                    "Origin": "https://attacker.example",
                },
            )
        self.assertEqual(403, cross_origin.status_code)
        load_registry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
