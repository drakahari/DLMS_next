"""Characterization coverage for the Reset & Remove settings view."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from markupsafe import escape

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


class ResetRemoveSettingsTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    def _page(self):
        response = self.client.get("/settings/reset-remove")
        self.assertEqual(200, response.status_code)
        return response.get_data(as_text=True)

    def test_route_uses_external_template_and_preserves_context(self):
        with mock.patch.object(
            dlms, "render_template", wraps=dlms.render_template
        ) as render_template:
            response = self.client.get("/settings/reset-remove")

        self.assertEqual(200, response.status_code)
        render_template.assert_called_once_with(
            "settings/reset-remove.html",
            app_data_dir=dlms.APP_DATA_DIR,
        )
        self.assertTrue(
            (Path(dlms.TEMPLATE_ROOT) / "settings" / "reset-remove.html").is_file()
        )

    def test_get_preserves_destructive_copy_navigation_and_accessibility(self):
        page = self._page()

        self.assertIn("SETTINGS / RESET &amp; REMOVE", page)
        self.assertIn(
            "Scoped resets create safety backups; permanent removal does not.", page
        )
        self.assertIn(
            "This action cannot be undone unless you have a backup.", page
        )
        self.assertIn(
            "This action has no automatic recovery backup.", page
        )
        self.assertIn(
            "Nothing outside the configured DLMS application-data directory is intentionally deleted.",
            page,
        )
        self.assertIn(
            "Neither action removes the executable/source installation.", page
        )
        self.assertIn('id="clearDBBtn" class="settings-danger-button" type="button"', page)
        self.assertIn(
            'id="removeAllDlmsDataBtn" class="settings-critical-button" type="button" disabled',
            page,
        )
        self.assertIn(
            '<label class="settings-field-label" for="removeDlmsConfirmation">', page
        )
        self.assertIn('autocomplete="off" spellcheck="false"', page)
        self.assertIn('id="clearDBStatus" class="settings-operation-status" aria-live="polite"', page)
        self.assertIn('id="resetStatus" class="settings-operation-status" aria-live="polite"', page)
        self.assertIn('aria-label="Toggle navigation"', page)
        self.assertIn('aria-controls="dashboardSidebar"', page)
        self.assertIn('aria-expanded="false"', page)
        for target in ("/settings", "/history", "/settings/backup"):
            self.assertIn(f"location.href='{target}'", page)
        self.assertIn('<script src="/static/nav-normalize.js"></script>', page)

    def test_scoped_reset_endpoints_methods_confirmations_and_states_are_unchanged(self):
        page = self._page()
        expected_buttons = (
            ("/api/reset_learning_intelligence", "Learning Intelligence"),
            ("/api/reset_quiz_library", "Quiz Library & Results"),
            ("/api/reset_source_content", "Imported / Source Content"),
            ("/api/reset_app_settings", "Application Settings"),
            ("/api/reset_all_data", "DLMS to Fresh State"),
        )
        for endpoint, label in expected_buttons:
            with self.subTest(endpoint=endpoint):
                self.assertIn(f'data-endpoint="{endpoint}"', page)
                self.assertIn(f'data-label="{label}"', page)

        self.assertIn(
            'data-confirm-text="Reset Learning Intelligence?&#10;&#10;This clears the answer evidence used for mastery, recommendations, diagnostics, and scheduled review. Your quizzes, concepts/tags, Study Packs, settings, saved attempts, and missed-question history will remain.&#10;&#10;DLMS will create a safety backup first. Continue?"',
            page,
        )
        self.assertIn(
            "DLMS will create a safety backup first, then perform this reset.\\n\\nContinue?",
            page,
        )
        self.assertIn(
            'fetch(btn.dataset.endpoint,{method:"POST"})', page
        )
        self.assertIn(
            'document.querySelectorAll(".resetAction").forEach(b=>b.disabled=true)',
            page,
        )
        self.assertIn(
            'resetStatus.textContent=`Creating safety backup and resetting ${label}...`',
            page,
        )
        self.assertIn(
            'resetStatus.textContent=`✅ ${label} reset completed. Safety backup: ${data.backup||"created"}`',
            page,
        )
        self.assertIn(
            'resetStatus.textContent=`❌ Reset failed: ${err.message}`', page
        )
        self.assertIn(
            'document.querySelectorAll(".resetAction").forEach(b=>b.disabled=false)',
            page,
        )
        self.assertIn("location.reload()", page)

    def test_history_clear_confirmation_request_and_status_contract_is_unchanged(self):
        page = self._page()

        self.assertIn(
            "Clear all saved quiz attempts and missed-question history?\\n\\nYour quizzes will remain available.\\n\\nCreate a backup first if you may need this history later.",
            page,
        )
        self.assertIn('fetch("/api/clear_db_history",{method:"POST"})', page)
        self.assertIn('clearDBBtn.disabled=true', page)
        self.assertIn('clearDBStatus.textContent="Clearing saved history..."', page)
        self.assertIn(
            'clearDBStatus.textContent="✅ Saved attempt and missed-question history cleared."',
            page,
        )
        self.assertIn(
            'clearDBStatus.textContent="❌ History clear failed. Check the server log."',
            page,
        )
        self.assertIn('finally{clearDBBtn.disabled=false}', page)

    def test_permanent_removal_phrase_request_shutdown_and_failure_contract_is_unchanged(self):
        page = self._page()

        self.assertIn(
            'placeholder="REMOVE DLMS DATA"', page
        )
        self.assertIn(
            'removeBtn.disabled=removeConfirm.value.trim()!=="REMOVE DLMS DATA"',
            page,
        )
        self.assertIn(
            'if(phrase!=="REMOVE DLMS DATA")return', page
        )
        self.assertIn(
            "☠ PERMANENT DLMS DATA REMOVAL ☠\\n\\nThis will delete the entire DLMS application-data directory INCLUDING ALL BACKUPS, then shut DLMS down.\\n\\nThe executable/source installation will remain.\\n\\nThis cannot be undone unless you copied a backup somewhere outside DLMS.\\n\\nContinue?",
            page,
        )
        self.assertIn(
            'fetch("/api/remove_all_dlms_data",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({confirmation:phrase})})',
            page,
        )
        self.assertIn(
            'document.querySelectorAll("button,input").forEach(el=>el.disabled=true)',
            page,
        )
        self.assertIn(
            'resetStatus.textContent="Permanently removing DLMS runtime data and shutting down..."',
            page,
        )
        self.assertIn(
            'resetStatus.textContent="✅ DLMS runtime data removed. DLMS is shutting down. The executable/source installation was preserved."',
            page,
        )
        self.assertIn(
            'resetStatus.textContent=`❌ Permanent removal failed: ${err.message}`',
            page,
        )
        self.assertIn(
            'document.querySelectorAll("button,input").forEach(el=>el.disabled=false)',
            page,
        )
        self.assertIn(
            "DLMS runtime data has been removed, including backups.\\n\\nDLMS will now shut down.\\n\\nThe executable/source installation was NOT removed.",
            page,
        )
        removal_handler = page[page.index('removeBtn.addEventListener("click"') :]
        self.assertNotIn("location.reload()", removal_handler)
        self.assertNotIn("location.href", removal_handler)

    def test_displayed_data_directory_is_html_escaped_outside_javascript(self):
        hostile = '</script><img src=x onerror="attack()">&\u2028\u2029'
        with mock.patch.object(dlms, "APP_DATA_DIR", hostile):
            page = self._page()

        self.assertIn(str(escape(hostile)), page)
        self.assertNotIn(hostile, page)
        self.assertNotIn('<img src=x onerror="attack()">', page)
        self.assertEqual(2, page.count("</script>"))
        self.assertIn("\u2028\u2029", page)
        self.assertNotIn("{{ app_data_dir }}", page)

        template = (
            Path(dlms.TEMPLATE_ROOT) / "settings" / "reset-remove.html"
        ).read_text(encoding="utf-8")
        inline_script = template.split("<script>", 1)[1].split("</script>", 1)[0]
        self.assertNotIn("{{", inline_script)
        self.assertNotIn("{%", inline_script)

    def test_destructive_api_requests_require_csrf_before_handlers_run(self):
        with mock.patch.object(dlms, "get_db") as get_db:
            history = self.client.post("/api/clear_db_history")
        self.assertEqual(400, history.status_code)
        get_db.assert_not_called()

        with mock.patch.object(dlms, "_run_reset_with_backup") as reset:
            scoped = self.client.post("/api/reset_all_data")
        self.assertEqual(400, scoped.status_code)
        reset.assert_not_called()

        with mock.patch.object(dlms, "_remove_all_dlms_runtime_data_core") as remove, \
             mock.patch.object(dlms, "_schedule_post_removal_shutdown") as shutdown:
            permanent = self.client.post(
                "/api/remove_all_dlms_data",
                json={"confirmation": "REMOVE DLMS DATA"},
            )
        self.assertEqual(400, permanent.status_code)
        remove.assert_not_called()
        shutdown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
