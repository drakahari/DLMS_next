"""Characterization coverage for the guided Law creation/import views."""

import html
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from markupsafe import escape

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import law as law_routes
from tests.csrf_test_utils import csrf_token


class LawGuidedWorkflowTemplateTests(unittest.TestCase):
    def setUp(self):
        self.content_packs_patcher = mock.patch.object(
            dlms, "discover_content_packs", return_value={}
        )
        self.content_packs_patcher.start()
        self.addCleanup(self.content_packs_patcher.stop)
        self.client = dlms.app.test_client()
        self.csrf = csrf_token(self.client, "/law")

    def _create_get(self, registry):
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Workflow Portal"
        ) as title_loader, mock.patch.object(
            dlms, "load_law_registry", return_value=registry
        ) as registry_loader:
            response = self.client.get("/law/create")
        self.assertEqual(200, response.status_code)
        title_loader.assert_called_once_with()
        registry_loader.assert_called_once_with()
        return response.get_data(as_text=True)

    def _import_get(self, registry, query=""):
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Workflow Portal"
        ) as title_loader, mock.patch.object(
            dlms, "load_law_registry", return_value=registry
        ) as registry_loader:
            response = self.client.get(f"/law/import{query}")
        self.assertEqual(200, response.status_code)
        title_loader.assert_called_once_with()
        registry_loader.assert_called_once_with()
        return response.get_data(as_text=True)

    def assert_law_shell(self, page, heading):
        self.assertIn(f"<h1>{heading}</h1>", page)
        self.assertIn(
            'class="dashboard-nav-item active" href="/law" aria-current="page"',
            page,
        )
        self.assertIn('<nav class="dashboard-nav" aria-label="Primary navigation">', page)
        self.assertIn(
            '<nav class="dashboard-nav dashboard-nav-system" aria-label="System navigation">',
            page,
        )
        self.assertIn('aria-label="Toggle navigation"', page)
        self.assertIn('aria-controls="dashboardSidebar"', page)
        self.assertIn('aria-expanded="false"', page)
        self.assertIn('<script src="/static/nav-normalize.js"></script>', page)

    def test_create_get_defaults_fields_actions_navigation_and_empty_prompt_state(self):
        page = self._create_get({"folders": ["Torts", "Contracts"]})

        self.assert_law_shell(page, "Create Case Review")
        self.assertIn('<form method="POST" action="/law/create" class="law-form">', page)
        self.assertIn(
            'name="case_name" value="" required\n                           '
            'placeholder="Example: Palsgraf v. Long Island Railroad Co."',
            page,
        )
        self.assertIn('<option value="Torts" selected>Torts</option>', page)
        self.assertIn('<option value="Contracts" >Contracts</option>', page)
        self.assertIn('<option value="chatgpt" selected>ChatGPT</option>', page)
        for field in (
            "case_name",
            "course",
            "ai_provider",
            "include_case_brief",
            "include_socratic",
            "include_irac",
            "include_flashcards",
        ):
            self.assertIn(f'name="{field}"', page)
        for checkbox in (
            "include_case_brief",
            "include_socratic",
            "include_irac",
            "include_flashcards",
        ):
            self.assertRegex(page, rf'name="{checkbox}"\s+checked')
        self.assertIn("Generate AI Prompt", page)
        self.assertIn("location.href='/law/import'", page)
        self.assertIn("location.href='/law'", page)
        self.assertNotIn('id="lawPromptBox"', page)
        self.assertNotIn('name="csrf_token"', page)

    def test_create_empty_folder_fallback_and_missing_case_validation_prompt(self):
        page = self._create_get({"folders": []})
        self.assertIn('<option value="Torts" selected>Torts</option>', page)
        self.assertEqual(1, page.count('<option value="Torts"'))
        self.assertNotIn('id="lawPromptBox"', page)

        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Workflow Portal"
        ), mock.patch.object(
            dlms, "load_law_registry", return_value={"folders": []}
        ), mock.patch.object(
            dlms._law_service, "start_pending_case_workflow"
        ) as starter:
            response = self.client.post(
                "/law/create",
                data={
                    "csrf_token": self.csrf,
                    "case_name": "   ",
                    "course": "   ",
                    "ai_provider": "unknown",
                },
            )

        self.assertEqual(200, response.status_code)
        posted = response.get_data(as_text=True)
        self.assertIn("Please enter a case name before generating the AI prompt.", posted)
        self.assertIn('id="lawPromptBox"', posted)
        self.assertIn("No custom AI URL is configured for Local / Custom.", posted)
        self.assertNotIn("Copy Prompt &amp; Open AI", posted)
        for checkbox in (
            "include_case_brief",
            "include_socratic",
            "include_irac",
            "include_flashcards",
        ):
            self.assertNotRegex(posted, rf'name="{checkbox}"\s+checked')
        starter.assert_not_called()

    def test_create_prompt_pending_state_selection_escaping_and_tojson_boundaries(self):
        case_name = (
            'Case & </textarea><script id="caseInjected">bad()</script> '
            '\u2028line\u2029paragraph'
        )
        course = 'Torts & <b id="courseInjected">Advanced</b>'
        provider_url = 'https://example.test/open?</script>&q="quoted"\'single\'\u2028\u2029'
        prompt_template = "PREFIX\nCASE={{case_name}}\nCOURSE={{course}}\nSECTIONS:\n{{study_sections}}\nSUFFIX"
        registry = {"folders": ["Contracts", course]}
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Workflow Portal"
        ), mock.patch.object(
            dlms, "load_law_registry", return_value=registry
        ), mock.patch.object(
            dlms, "load_portal_config",
            return_value={
                "ai_custom_url": provider_url,
                "law_ai_prompt_template": prompt_template,
            },
        ), mock.patch.object(
            dlms._law_service, "start_pending_case_workflow"
        ) as starter, mock.patch.object(dlms, "datetime") as datetime_mock:
            datetime_mock.now.return_value.isoformat.return_value = "2026-09-07T12:34:56"
            response = self.client.post(
                "/law/create",
                data={
                    "csrf_token": self.csrf,
                    "case_name": case_name,
                    "course": course,
                    "ai_provider": "LOCAL",
                    "include_case_brief": "on",
                    "include_irac": "on",
                },
            )

        self.assertEqual(200, response.status_code)
        page = response.get_data(as_text=True)
        expected_slug = dlms.make_law_case_slug(case_name)
        starter.assert_called_once_with(
            registry,
            case_name=case_name,
            case_slug=expected_slug,
            course=course,
            created_at="2026-09-07T12:34:56",
            save_law_registry=dlms.save_law_registry,
        )
        prompt_match = re.search(
            r'(?s)<textarea id="lawPromptBox" class="law-prompt-box" rows="18" '
            r'aria-labelledby="lawGeneratedPromptHeading">(.*?)</textarea>',
            page,
        )
        self.assertIsNotNone(prompt_match)
        prompt = html.unescape(prompt_match.group(1))
        self.assertTrue(prompt.startswith(f"PREFIX\nCASE={case_name}\nCOURSE={course}\nSECTIONS:\n"))
        self.assertIn("1. Case Brief\n   - Full case name and citation", prompt)
        self.assertIn("3. IRAC Drill\n   - One short practice fact pattern", prompt)
        self.assertNotIn("2. Socratic Review", prompt)
        self.assertNotIn("4. Rule Flashcards", prompt)
        self.assertTrue(prompt.endswith("\nSUFFIX"))
        self.assertIn(f'value="{escape(case_name)}" required', page)
        self.assertIn(f'<option value="{escape(course)}" selected>{escape(course)}</option>', page)
        self.assertIn('<option value="local" selected>Local / Custom</option>', page)
        self.assertRegex(page, r'name="include_case_brief"\s+checked')
        self.assertRegex(page, r'name="include_irac"\s+checked')
        self.assertNotRegex(page, r'name="include_socratic"\s+checked')
        self.assertNotRegex(page, r'name="include_flashcards"\s+checked')

        serialized_match = re.search(
            r"onclick='copyPromptAndOpenAi\((.*?)\)'", page
        )
        self.assertIsNotNone(serialized_match)
        serialized = serialized_match.group(1)
        self.assertEqual(provider_url, json.loads(serialized))
        self.assertIn(r"\u003c/script\u003e", serialized)
        self.assertIn(r"\u0026", serialized)
        self.assertIn(r"\u0027", serialized)
        self.assertIn(r"\u2028", serialized)
        self.assertIn(r"\u2029", serialized)
        self.assertNotIn("</script>", serialized.lower())
        self.assertNotIn("\u2028", serialized.replace(r"\u2028", ""))
        self.assertNotIn("\u2029", serialized.replace(r"\u2029", ""))
        self.assertNotIn('<script id="caseInjected">', page)
        self.assertNotIn('<b id="courseInjected">', page)

    def test_import_get_pending_metadata_authority_and_explicit_metadata_fallback(self):
        empty = self._import_get({})
        self.assert_law_shell(empty, "Import Case Packet")
        self.assertIn("No active case workflow.", empty)
        self.assertIn("location.href='/law/create'", empty)
        self.assertNotIn('class="law-workflow-banner"', empty)
        self.assertIn('<input type="hidden" name="case_name" value="">', empty)
        self.assertIn('<input type="hidden" name="case_slug" value="">', empty)

        pending = {
            "pending_case_workflow": {
                "case_name": 'Pending & <b id="pendingInjected">Case</b>',
                "case_slug": "pending-case",
                "course": "Torts",
            }
        }
        page = self._import_get(pending)
        self.assertIn('class="law-workflow-banner"', page)
        self.assertIn(f"<strong>{escape(pending['pending_case_workflow']['case_name'])}</strong>", page)
        self.assertIn("<small>File slug: pending-case</small>", page)
        self.assertIn('<form method="POST" action="/law/workflow/cancel"', page)
        self.assertIn(
            "Cancel the active Law Study workflow? This will not delete saved imports or case reviews.",
            page,
        )
        self.assertNotIn('<b id="pendingInjected">', page)

        protected = self._import_get(
            pending,
            "?case_name=Query%20Case&case_slug=query-slug&workflow_cancelled=1",
        )
        self.assertIn(
            f"<strong>{escape(pending['pending_case_workflow']['case_name'])}</strong>",
            protected,
        )
        self.assertIn("<small>File slug: pending-case</small>", protected)
        self.assertNotIn("<strong>Query Case</strong>", protected)
        self.assertNotIn("<small>File slug: query-slug</small>", protected)
        self.assertIn("Active case workflow cancelled.", protected)
        self.assertIn("Pending case metadata has been cleared.", protected)

        explicit = self._import_get(
            {}, "?case_name=Query%20Case&case_slug=query-slug"
        )
        self.assertIn("<strong>Query Case</strong>", explicit)
        self.assertIn("<small>File slug: query-slug</small>", explicit)
        self.assertIn(
            '<input type="hidden" name="case_name" value="Query Case">', explicit
        )
        self.assertIn(
            '<input type="hidden" name="case_slug" value="query-slug">', explicit
        )

    def test_import_form_contract_preview_counts_raw_escaping_and_unknown_action(self):
        raw = '  Sources Used\nRaw & </textarea><script id="rawInjected">bad()</script> \u2028\u2029  '
        registry = {
            "pending_case_workflow": {
                "case_name": "Pending Case",
                "case_slug": "pending-case",
            }
        }
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Workflow Portal"
        ), mock.patch.object(
            dlms, "load_law_registry", return_value=registry
        ), mock.patch.object(dlms, "save_law_raw_packet") as saver:
            response = self.client.post(
                "/law/import",
                data={
                    "csrf_token": self.csrf,
                    "raw_packet": raw,
                    "action": "unexpected-action",
                },
            )

        self.assertEqual(200, response.status_code)
        page = response.get_data(as_text=True)
        stripped = raw.strip()
        self.assertIn('<form method="POST" action="/law/import" class="law-form">', page)
        self.assertIn(
            '<label class="law-field law-field-wide" for="lawRawPacketInput">', page
        )
        self.assertIn('id="lawRawPacketInput" name="raw_packet"', page)
        self.assertIn('<input type="hidden" name="case_name" value="Pending Case">', page)
        self.assertIn('<input type="hidden" name="case_slug" value="pending-case">', page)
        self.assertIn('name="raw_packet" class="law-import-textarea" rows="22"', page)
        self.assertIn(str(escape(stripped)), page)
        self.assertNotIn('<script id="rawInjected">', page)
        self.assertEqual(2, page.count("</script>"))
        self.assertEqual(1, page.count("</textarea>"))
        self.assertIn(f"<span>Lines</span><strong>{len(stripped.splitlines())}</strong>", page)
        self.assertIn(f"<span>Characters</span><strong>{len(stripped)}</strong>", page)
        self.assertIn("<span>Status</span><strong>Ready</strong>", page)
        for action, label in (
            ("save_and_preview", "Save &amp; Preview Case Packet"),
            ("preview", "Check Pasted Text"),
            ("save_raw", "Save Raw Packet Only"),
        ):
            self.assertIn(f'name="action" value="{action}"', page)
            self.assertIn(label, page)
        self.assertNotIn('name="csrf_token"', page)
        saver.assert_not_called()

    def test_import_save_raw_success_failure_empty_and_preview_redirect(self):
        registry = {"pending_case_workflow": {"case_name": "Case", "case_slug": "case"}}
        common = {
            "csrf_token": self.csrf,
            "raw_packet": "  1. Case Brief\nFacts  ",
        }
        with mock.patch.object(dlms, "load_law_registry", return_value=registry), mock.patch.object(
            dlms, "save_law_raw_packet", return_value="saved-packet.txt"
        ) as saver:
            saved = self.client.post(
                "/law/import",
                data={
                    **common,
                    "action": "save_raw",
                    "case_name": "Stale bookmarked case",
                    "case_slug": "stale-bookmarked-slug",
                },
            )
            redirected = self.client.post(
                "/law/import", data={**common, "action": "save_and_preview"}
            )

        self.assertEqual(200, saved.status_code)
        saved_page = saved.get_data(as_text=True)
        self.assertIn("Saved raw case packet as saved-packet.txt", saved_page)
        self.assertIn(
            '<div class="law-notice success" role="status" aria-live="polite"><strong>Saved raw case packet as '
            "saved-packet.txt</strong></div>",
            saved_page,
        )
        self.assertIn("Import Summary", saved_page)
        self.assertEqual(302, redirected.status_code)
        self.assertEqual(
            "/law/imports/saved-packet.txt", redirected.headers["Location"]
        )
        self.assertEqual(
            [mock.call("1. Case Brief\nFacts", "case")] * 2,
            saver.call_args_list,
        )

        with mock.patch.object(dlms, "load_law_registry", return_value=registry), mock.patch.object(
            dlms, "save_law_raw_packet", side_effect=OSError("disk unavailable")
        ), mock.patch("builtins.print") as printer:
            failed = self.client.post(
                "/law/import", data={**common, "action": "save_raw"}
            )

        self.assertEqual(200, failed.status_code)
        failed_page = failed.get_data(as_text=True)
        self.assertIn("Error: failed to save raw case packet.", failed_page)
        self.assertIn(
            '<div class="law-notice error" role="alert"><strong>Error: failed to save raw '
            "case packet.</strong></div>",
            failed_page,
        )
        self.assertNotIn('<div class="law-notice success">', failed_page)
        self.assertIn(
            mock.call("[LAW IMPORT ERROR] Failed saving raw packet: disk unavailable"),
            printer.call_args_list,
        )

        with mock.patch.object(dlms, "load_law_registry", return_value={}):
            empty = self.client.post(
                "/law/import",
                data={"csrf_token": self.csrf, "raw_packet": "   ", "action": "save_raw"},
            )
        self.assertEqual(200, empty.status_code)
        empty_page = empty.get_data(as_text=True)
        self.assertNotIn("Import Summary", empty_page)
        self.assertNotIn("failed to save", empty_page)

    def test_cancel_transition_redirect_and_no_pending_behavior(self):
        registry = {"pending_case_workflow": {"case_name": "Active"}, "cases": []}
        with mock.patch.object(dlms, "load_law_registry", return_value=registry), mock.patch.object(
            dlms._law_service, "cancel_pending_case_workflow"
        ) as cancel:
            response = self.client.post(
                "/law/workflow/cancel",
                data={"csrf_token": self.csrf},
                follow_redirects=False,
            )
        self.assertEqual(302, response.status_code)
        self.assertEqual("/law/import?workflow_cancelled=1", response.headers["Location"])
        cancel.assert_called_once_with(
            registry,
            save_law_registry=dlms.save_law_registry,
        )

        with mock.patch.object(dlms, "load_law_registry", return_value={}), mock.patch.object(
            dlms._law_service, "cancel_pending_case_workflow"
        ) as absent_cancel:
            absent = self.client.post(
                "/law/workflow/cancel",
                data={"csrf_token": self.csrf},
                follow_redirects=False,
            )
        self.assertEqual(302, absent.status_code)
        self.assertEqual("/law/import?workflow_cancelled=1", absent.headers["Location"])
        absent_cancel.assert_not_called()

    def test_inline_scripts_and_accessibility_contracts_are_preserved(self):
        create = self._create_get({"folders": ["Torts"]})
        imported = self._import_get({})

        for page in (create, imported):
            with self.subTest(title=page.split("<title>", 1)[1].split("</title>", 1)[0]):
                inline_scripts = re.findall(r"<script>(.*?)</script>", page, re.DOTALL)
                self.assertTrue(inline_scripts)
                self.assertTrue(all("{{" not in script for script in inline_scripts))
                self.assertIn(
                    'confirm("Shut down DLMS? You will need to restart it manually.")',
                    inline_scripts[-1],
                )
                self.assertIn('fetch("/api/shutdown", { method: "POST" })', inline_scripts[-1])
                self.assertIn("sidebar.classList.toggle(\"open\")", inline_scripts[-1])
        self.assertIn('id="lawPromptBox"', self.client.post(
            "/law/create",
            data={"csrf_token": self.csrf, "case_name": "", "ai_provider": "chatgpt"},
        ).get_data(as_text=True))
        self.assertIn('placeholder="Paste the AI-generated case brief, Socratic review, IRAC drill, and flashcards here..."', imported)

    def test_create_route_uses_external_template_with_unchanged_get_context(self):
        folders = ["Torts", "Contracts"]
        registry = {"folders": folders}
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Portal"
        ), mock.patch.object(
            dlms, "load_law_registry", return_value=registry
        ), mock.patch.object(
            law_routes, "render_template", return_value="rendered"
        ) as renderer:
            response = self.client.get("/law/create")

        self.assertEqual(200, response.status_code)
        self.assertEqual("rendered", response.get_data(as_text=True))
        renderer.assert_called_once_with(
            "law/create.html",
            portal_title="Law Portal",
            law_folders=folders,
            case_name="",
            case_slug="",
            course="Torts",
            ai_provider="chatgpt",
            generated_prompt="",
            ai_provider_url="",
            include_case_brief=True,
            include_socratic=True,
            include_irac=True,
            include_flashcards=True,
        )
        self.assertTrue((Path(dlms.TEMPLATE_ROOT) / "law" / "create.html").is_file())

    def test_import_route_uses_external_template_with_unchanged_get_context(self):
        registry = {
            "pending_case_workflow": {
                "case_name": "Pending Case",
                "case_slug": "pending-case",
            }
        }
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Portal"
        ), mock.patch.object(
            dlms, "load_law_registry", return_value=registry
        ), mock.patch.object(
            law_routes, "render_template", return_value="rendered"
        ) as renderer:
            response = self.client.get("/law/import")

        self.assertEqual(200, response.status_code)
        self.assertEqual("rendered", response.get_data(as_text=True))
        renderer.assert_called_once_with(
            "law/import.html",
            portal_title="Law Portal",
            case_name="Pending Case",
            case_slug="pending-case",
            raw_packet="",
            packet_submitted=False,
            line_count=0,
            char_count=0,
            saved_file="",
            save_message="",
            save_message_category="",
        )
        self.assertTrue((Path(dlms.TEMPLATE_ROOT) / "law" / "import.html").is_file())


if __name__ == "__main__":
    unittest.main()
