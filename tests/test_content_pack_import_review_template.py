"""Characterization coverage for the Content Pack import review view."""

import unittest
from pathlib import Path
from urllib.parse import quote
from unittest import mock

from markupsafe import escape

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


class ContentPackImportReviewTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    @staticmethod
    def _metadata(**overrides):
        metadata = {
            "uploaded_name": "DLMS_Study_sample.zip",
            "file_count": 7,
            "uncompressed_bytes": 1572864,
        }
        metadata.update(overrides)
        return metadata

    @staticmethod
    def _report(**overrides):
        report = {
            "valid": True,
            "pack_name": "Sample Study Pack",
            "dataset_count": 2,
            "checks": [
                {"status": "PASS", "name": "Manifest", "detail": "Manifest accepted."},
                {"status": "INFO", "name": "Metadata", "detail": "Optional metadata absent."},
            ],
            "errors": [],
            "warnings": ["Optional source note is absent."],
        }
        report.update(overrides)
        return report

    def _review(self, token, metadata, report):
        with mock.patch.object(
            dlms,
            "_load_staged_content_pack",
            return_value=("stage", "pack", metadata),
        ), mock.patch.object(
            dlms, "_validate_staged_content_pack", return_value=report
        ):
            response = self.client.get(
                "/content-packs/import/" + quote(token, safe="")
            )
        self.assertEqual(200, response.status_code)
        return response.get_data(as_text=True)

    def test_route_uses_external_template_and_preserves_exact_context(self):
        metadata = self._metadata()
        report = self._report()
        with mock.patch.object(
            dlms,
            "_load_staged_content_pack",
            return_value=("stage", "pack", metadata),
        ), mock.patch.object(
            dlms, "_validate_staged_content_pack", return_value=report
        ), mock.patch.object(
            dlms, "render_template", wraps=dlms.render_template
        ) as render_template:
            response = self.client.get("/content-packs/import/review-token")

        self.assertEqual(200, response.status_code)
        render_template.assert_called_once_with(
            "content_packs/import-review.html",
            token="review-token",
            metadata=metadata,
            report=report,
            ai_workflow=False,
            return_url="/content-packs",
            return_label="Content Packs",
            medical_pack_installed=True,
        )
        self.assertTrue(
            (
                Path(dlms.TEMPLATE_ROOT)
                / "content_packs"
                / "import-review.html"
            ).is_file()
        )

    def test_manual_valid_review_preserves_metadata_forms_routes_and_accessibility(self):
        token = "review-token"
        page = self._review(token, self._metadata(), self._report())

        self.assertIn("CONTENT PACK IMPORT", page)
        self.assertNotIn("AI STUDY PACK WORKFLOW", page)
        self.assertIn("READY TO INSTALL", page)
        self.assertIn("Sample Study Pack", page)
        self.assertIn("DLMS_Study_sample.zip · 7 files · 1.5 MB expanded", page)
        self.assertIn("2 datasets", page)
        self.assertIn("<span>Passed</span><strong>1</strong>", page)
        self.assertIn("<span>Warnings</span><strong>1</strong>", page)
        self.assertIn("<span>Errors</span><strong>0</strong>", page)
        self.assertIn(
            '<form class="pack-review-install-form" id="packReviewInstallForm" method="POST" action="/content-packs/import/review-token/install">',
            page,
        )
        self.assertIn(
            '<input type="checkbox" name="confirm_install" value="yes" required>',
            page,
        )
        self.assertIn(
            '<button class="medical-primary-button" type="submit" form="packReviewInstallForm">Install Study Pack</button>',
            page,
        )
        self.assertIn(
            '<form class="pack-review-cancel-form" method="POST" action="/content-packs/import/review-token/cancel">',
            page,
        )
        self.assertIn("Cancel &amp; Remove Staging Files", page)
        self.assertIn('href="/content-packs">← Back to Content Packs</a>', page)
        self.assertIn('aria-label="Toggle navigation"', page)
        self.assertIn('aria-controls="dashboardSidebar"', page)
        self.assertIn('aria-expanded="false"', page)
        self.assertIn(
            'class="dashboard-nav-item active" href="/content-packs"', page
        )
        self.assertIn('<script src="/static/nav-normalize.js"></script>', page)

    def test_invalid_review_preserves_blocking_messages_and_cancel_only_state(self):
        report = self._report(
            valid=False,
            pack_name="",
            dataset_count=0,
            checks=[{"status": "FAIL", "name": "Manifest", "detail": "Invalid."}],
            errors=["Manifest is missing an id."],
            warnings=[],
        )
        page = self._review(
            "blocked-token",
            self._metadata(uploaded_name="blocked.zip", file_count=1, uncompressed_bytes=0),
            report,
        )

        self.assertIn("INSTALL BLOCKED", page)
        self.assertIn("<h2>blocked.zip</h2>", page)
        self.assertIn("blocked.zip · 1 files · 0.0 MB expanded", page)
        self.assertIn("0 datasets", page)
        self.assertIn("<h3>Blocking problems</h3>", page)
        self.assertIn("Manifest is missing an id.", page)
        self.assertIn(
            "Installation is disabled until the blocking validation problems are corrected.",
            page,
        )
        self.assertNotIn('id="packReviewInstallForm"', page)
        self.assertNotIn("Install Study Pack</button>", page)
        self.assertIn(
            'action="/content-packs/import/blocked-token/cancel"', page
        )

    def test_ai_review_preserves_workflow_steps_corrections_and_return_target(self):
        correction = "DLMS safely randomized the choices for 25 questions."
        metadata = self._metadata(
            workflow=dlms.CONTENT_PACK_AI_WORKFLOW,
            answer_position_corrections=[correction],
        )
        report = self._report(warnings=[])
        page = self._review("ai-token", metadata, report)

        self.assertIn("AI STUDY PACK WORKFLOW", page)
        self.assertIn(
            '<ol class="study-pack-workflow-steps" aria-label="AI Study Pack workflow">',
            page,
        )
        for step in ("Configure", "Generate Prompt", "Bring Back ZIP", "Validate", "Install", "Study"):
            self.assertIn(f">{step}<", page)
        self.assertIn(correction, page)
        self.assertIn('href="/study-packs/ai-builder"', page)
        self.assertIn("← Back to AI Study Pack Builder", page)

    def test_displayed_values_and_token_are_html_escaped_and_not_serialized_into_script(self):
        token = 'token"\'&<token>'
        values = {
            "uploaded_name": 'archive </script><img id="upload-injected"> & \"name\" \u2028\u2029.zip',
            "pack_name": 'Pack </script><svg id="pack-injected"> & \"name\"',
            "status": 'PASS\"><img id="status-injected">',
            "check_name": "Check <name> & value",
            "check_detail": 'Detail </script> & \"quoted\" \u2028\u2029',
            "warning": '<img id="warning-injected"> Warning & value',
            "error": '<svg id="error-injected"> Error & value',
        }
        metadata = self._metadata(uploaded_name=values["uploaded_name"])
        report = self._report(
            valid=False,
            pack_name=values["pack_name"],
            checks=[{
                "status": values["status"],
                "name": values["check_name"],
                "detail": values["check_detail"],
            }],
            warnings=[values["warning"]],
            errors=[values["error"]],
        )
        page = self._review(token, metadata, report)

        for value in values.values():
            self.assertIn(str(escape(value)), page)
        self.assertNotIn('<img id="upload-injected">', page)
        self.assertNotIn('<svg id="pack-injected">', page)
        self.assertNotIn('<img id="status-injected">', page)
        self.assertNotIn('<img id="warning-injected">', page)
        self.assertNotIn('<svg id="error-injected">', page)
        escaped_token = str(escape(token))
        self.assertIn(
            f'action="/content-packs/import/{escaped_token}/cancel"', page
        )
        self.assertNotIn(token, page)
        self.assertEqual(2, page.count("</script>"))
        inline_script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        self.assertEqual(
            "document.getElementById('menuButton')?.addEventListener('click',()=>document.getElementById('dashboardSidebar')?.classList.toggle('open'));",
            inline_script,
        )
        for value in values.values():
            self.assertNotIn(value, inline_script)

    def test_review_revalidates_and_unavailable_token_redirects_with_generic_message(self):
        metadata = self._metadata(workflow=dlms.CONTENT_PACK_AI_WORKFLOW)
        report = self._report()
        with mock.patch.object(
            dlms,
            "_load_staged_content_pack",
            return_value=("stage", "pack", metadata),
        ), mock.patch.object(
            dlms, "_validate_staged_content_pack", return_value=report
        ) as validate:
            response = self.client.get("/content-packs/import/live-token")

        self.assertEqual(200, response.status_code)
        validate.assert_called_once_with("pack", require_single_select=True)

        with mock.patch.object(
            dlms,
            "_load_staged_content_pack",
            side_effect=ValueError("private token/path detail"),
        ):
            response = self.client.get("/content-packs/import/expired-token")

        self.assertEqual(302, response.status_code)
        self.assertEqual("/content-packs", response.headers["Location"])
        with self.client.session_transaction() as session:
            self.assertEqual(
                [("error", "The Study Pack validation session is unavailable or expired.")],
                session.get("_flashes"),
            )
        self.assertNotIn(
            "private token/path detail", response.get_data(as_text=True)
        )

    def test_install_confirmation_and_cancel_routes_preserve_csrf_and_redirects(self):
        csrf = csrf_token(self.client, "/content-packs")
        with mock.patch.object(dlms, "_install_staged_content_pack") as install:
            response = self.client.post(
                "/content-packs/import/review-token/install",
                data={"csrf_token": csrf},
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual(
            "/content-packs/import/review-token", response.headers["Location"]
        )
        install.assert_not_called()

        with mock.patch.object(
            dlms,
            "_install_staged_content_pack",
            return_value={
                "status": "installed",
                "metadata": {},
                "pack_id": "sample",
                "installed": {"name": "Sample Study Pack"},
            },
        ) as install:
            response = self.client.post(
                "/content-packs/import/review-token/install",
                data={"csrf_token": csrf, "confirm_install": "yes"},
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual("/content-packs", response.headers["Location"])
        install.assert_called_once_with("review-token")

        with mock.patch.object(
            dlms, "_cancel_staged_content_pack", return_value={}
        ) as cancel:
            response = self.client.post(
                "/content-packs/import/review-token/cancel",
                data={"csrf_token": csrf},
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual("/content-packs", response.headers["Location"])
        cancel.assert_called_once_with("review-token")


if __name__ == "__main__":
    unittest.main()
