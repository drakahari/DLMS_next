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
        self.assertIn("You normally do not need to run this after updating DLMS.", page)
        self.assertIn("when DLMS specifically instructs you", page)
        self.assertIn("look stale or inconsistent with the current quiz interface", page)
        self.assertIn(
            "It does not change questions, answers, correctness, quiz or question IDs, concepts, lineage, folders, source or provenance details, scores, attempt history, learning events, or other learning history.",
            page,
        )
        self.assertIn('href="/admin/image-editor"', page)
        self.assertIn("Open Image Study Editor", page)
        self.assertIn(
            'id="rebuildAllBtn" class="build-primary-button" type="button" aria-describedby="rebuildDescription"', page
        )
        self.assertIn(
            'id="rebuildStatus" class="system-tools-status" role="status" aria-live="polite" aria-atomic="true"',
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
            "Rebuild all registered quiz pages from saved quiz data?\\n\\n", page
        )
        self.assertIn(
            "Only derived page files will be replaced. Questions, answers, IDs, lineage, folders, and learning history will not be changed.", page
        )
        self.assertIn("if (!ok) return;", page)
        self.assertIn("rebuildBtn.disabled = true;", page)
        self.assertIn(
            'rebuildStatus.textContent = "Rebuilding quiz pages...";', page
        )
        self.assertIn(
            'body: JSON.stringify({confirmation: "rebuild-all-quiz-pages"})', page
        )
        self.assertIn('throw new Error("Rebuild request failed")', page)
        self.assertIn(
            "`Complete: ${data.rebuilt} rebuilt, 0 failed.`",
            page,
        )
        self.assertIn("Finished with issues:", page)
        self.assertIn("Failed quizzes kept their previous page files.", page)
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

    def test_rebuild_endpoint_requires_confirmation_and_reports_batch_result(self):
        result = {
            "total": 3,
            "rebuilt": 2,
            "failed": [9],
        }
        with mock.patch.object(
            dlms, "_rebuild_registered_quiz_artifacts", return_value=result
        ) as rebuild_call:
            unconfirmed = self.client.post(
                "/admin/rebuild_all_quiz_html",
                json={},
                headers=csrf_headers(self.client, "/admin/maintenance"),
            )
            response = self.client.post(
                "/admin/rebuild_all_quiz_html",
                json={"confirmation": "rebuild-all-quiz-pages"},
                headers=csrf_headers(self.client, "/admin/maintenance"),
            )

        self.assertEqual(400, unconfirmed.status_code)
        self.assertIn("Confirmation is required", unconfirmed.get_json()["error"])
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "status": "partial",
                "total": 3,
                "rebuilt": 2,
                "failed": [9],
            },
            response.get_json(),
        )
        rebuild_call.assert_called_once_with()

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
