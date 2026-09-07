"""Characterization coverage for the read-only Law landing view."""

import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


class LawLandingTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    def _get(self, registry, portal_title="DLMS Test Portal"):
        with mock.patch.object(
            dlms, "get_portal_title", return_value=portal_title
        ) as title_loader, mock.patch.object(
            dlms, "load_law_registry", return_value=registry
        ) as registry_loader:
            response = self.client.get("/law")
        self.assertEqual(200, response.status_code)
        title_loader.assert_called_once_with()
        registry_loader.assert_called_once_with()
        return response.get_data(as_text=True)

    def test_empty_state_counts_summary_navigation_and_actions(self):
        page = self._get({"cases": [], "folders": []})

        self.assertIn("<title>Law Study - DLMS</title>", page)
        self.assertIn("<h1>Casework &amp; Review</h1>", page)
        self.assertIn(
            '<section class="law-hub-summary" aria-label="Law Study summary">',
            page,
        )
        self.assertIn("<span>Saved Cases</span><strong>0</strong><small>case reviews</small>", page)
        self.assertIn("<span>Courses</span><strong>0</strong><small>study folders</small>", page)
        self.assertIn("<span>Workflow</span><strong>AI Ready</strong>", page)
        self.assertIn('<section class="law-hub-grid" aria-label="Law Study tools">', page)
        self.assertIn('href="/law/create"', page)
        self.assertIn('href="/law/import"', page)
        self.assertIn('href="/law/cases"', page)
        self.assertIn('href="/law/imports"', page)
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
        self.assertIn('<button class="dashboard-shutdown" id="shutdownBtn" type="button">', page)

    def test_populated_state_uses_registry_lengths_without_rendering_case_metadata(self):
        hostile = 'Case </script><img id="lawCaseInjected"> & < > "   '
        registry = {
            "cases": [
                {
                    "id": "case-one",
                    "title": hostile,
                    "course": 'Torts <b id="lawCourseInjected">',
                    "file": "case-one.json",
                    "status": "draft",
                    "description": hostile,
                },
                {"id": "case-two", "title": "Second case"},
            ],
            "folders": [hostile, "Contracts", "Evidence"],
        }
        page = self._get(
            registry,
            portal_title='Portal <svg id="lawPortalInjected"> & unsafe',
        )

        self.assertIn("<span>Saved Cases</span><strong>2</strong><small>case reviews</small>", page)
        self.assertIn("<span>Courses</span><strong>3</strong><small>study folders</small>", page)
        for injected_id in (
            "lawCaseInjected",
            "lawCourseInjected",
            "lawPortalInjected",
        ):
            self.assertNotIn(injected_id, page)
        self.assertNotIn("case-one.json", page)
        self.assertNotIn("draft", page)
        self.assertNotIn(hostile, page)

    def test_fixed_cards_and_conditional_medical_navigation_are_preserved(self):
        page = self._get({"cases": [], "folders": []})

        for heading, copy in (
            ("Create Case Review", "Build a case brief, Socratic questions, IRAC drill, and flashcards."),
            ("Import Case Packet", "Paste AI-generated study output for preview and saving."),
            ("My Case Reviews", "Browse saved cases organized by course and topic."),
            ("Saved Imports", "Inspect, reparse, or manage raw packets retained from guided and manual imports."),
        ):
            with self.subTest(heading=heading):
                self.assertIn(f"<h2>{heading}</h2><p>{copy}</p>", page)
        self.assertIn('href="/medical"', page)
        self.assertIn('href="/medical/matching"', page)
        self.assertIn('href="/medical/anatomy"', page)
        self.assertIn(
            'href="/study-packs/ai-builder?domain=Medical&amp;from=medical"', page
        )
        self.assertIn("Future Study Modes", page)
        self.assertIn("Coming later", page)

    def test_landing_does_not_render_or_consume_flashed_messages(self):
        message = 'Law flash <b id="lawFlashInjected"> & pending'
        with self.client.session_transaction() as session:
            session["_flashes"] = [("success", message)]

        page = self._get({"cases": [], "folders": []})

        self.assertNotIn(message, page)
        self.assertNotIn("lawFlashInjected", page)
        with self.client.session_transaction() as session:
            self.assertEqual([("success", message)], session.get("_flashes"))

    def test_inline_javascript_shutdown_and_serialization_boundaries_are_preserved(self):
        hostile = 'Unused </script><img id="lawScriptInjected">   '
        page = self._get(
            {"cases": [{"title": hostile}], "folders": [hostile]},
            portal_title=hostile,
        )

        self.assertEqual(2, page.count("</script>"))
        inline_script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        self.assertNotIn(hostile, inline_script)
        self.assertNotIn("{{", inline_script)
        self.assertIn(
            'confirm("SHUTDOWN DLMS\\n\\nThis will stop the application.\\n\\n'
            'You will need to restart it manually.\\n\\nContinue?")',
            inline_script,
        )
        self.assertIn('fetch("/api/shutdown", { method: "POST" })', inline_script)
        self.assertIn("sidebar.classList.toggle(\"open\")", inline_script)
        self.assertIn("window.innerWidth > 820", inline_script)
        self.assertIn("DLMS has been shut down.", inline_script)
        self.assertIn("DLMS may already be shutting down.", inline_script)
        self.assertIn('<script src="/static/nav-normalize.js"></script>', page)

    def test_route_uses_external_template_with_unchanged_context(self):
        registry = {
            "cases": [{"id": "one"}, {"id": "two"}],
            "folders": ["Torts", "Contracts", "Evidence"],
        }
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Portal"
        ), mock.patch.object(
            dlms, "load_law_registry", return_value=registry
        ), mock.patch.object(
            dlms, "render_template", return_value="rendered"
        ) as renderer:
            response = self.client.get("/law")

        self.assertEqual(200, response.status_code)
        self.assertEqual("rendered", response.get_data(as_text=True))
        renderer.assert_called_once_with(
            "law/index.html",
            portal_title="Law Portal",
            law_registry=registry,
            saved_cases=2,
            course_count=3,
        )
        self.assertTrue((Path(dlms.TEMPLATE_ROOT) / "law" / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
