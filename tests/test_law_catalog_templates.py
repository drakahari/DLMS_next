"""Characterization coverage for the read-only Law catalog views."""

import unittest
from pathlib import Path
from unittest import mock

from markupsafe import escape

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


class LawCatalogTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    def _get_imports(self, imports, query=""):
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Catalog Portal"
        ) as title_loader, mock.patch.object(
            dlms._law_service, "list_law_raw_imports", return_value=imports
        ) as import_loader:
            response = self.client.get(f"/law/imports{query}")

        self.assertEqual(200, response.status_code)
        title_loader.assert_called_once_with()
        import_loader.assert_called_once_with(
            dlms.LAW_IMPORTS_FOLDER,
            from_timestamp=dlms.datetime.fromtimestamp,
            imports=[],
            makedirs=dlms.os.makedirs,
            listdir=dlms.os.listdir,
            join_path=dlms.os.path.join,
            isfile=dlms.os.path.isfile,
            stat_file=dlms.os.stat,
        )
        return response.get_data(as_text=True)

    def _get_cases(self, registry, query=""):
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Catalog Portal"
        ) as title_loader, mock.patch.object(
            dlms, "load_law_registry", return_value=registry
        ) as registry_loader:
            response = self.client.get(f"/law/cases{query}")

        self.assertEqual(200, response.status_code)
        title_loader.assert_called_once_with()
        registry_loader.assert_called_once_with()
        return response.get_data(as_text=True)

    def assert_catalog_shell(self, page, heading):
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
        self.assertIn(
            '<button class="dashboard-shutdown" id="shutdownBtn" type="button">',
            page,
        )
        self.assertIn('<script src="/static/nav-normalize.js"></script>', page)

    def test_import_catalog_empty_state_navigation_and_actions(self):
        page = self._get_imports([])

        self.assert_catalog_shell(page, "Saved Law Imports")
        self.assertIn('<span class="law-count-pill">0 saved</span>', page)
        self.assertIn("No saved imports yet", page)
        self.assertIn("Use Import Case Packet to paste and save", page)
        self.assertNotIn('class="law-record-row"', page)
        self.assertIn("location.href='/law/import'", page)
        self.assertIn("location.href='/law'", page)

    def test_import_catalog_populated_metadata_actions_and_escaping(self):
        filename = 'raw & <tag id="importInjected"> "double" \'single\' </script> \u2028\u2029.txt'
        size = '<b id="sizeInjected">42</b>'
        modified = '<svg id="modifiedInjected">2026</svg>'
        page = self._get_imports(
            [{"filename": filename, "size": size, "modified": modified}]
        )
        escaped_filename = str(escape(filename))

        self.assertIn('<span class="law-count-pill">1 saved</span>', page)
        self.assertIn(f"<h3>{escaped_filename}</h3>", page)
        self.assertIn(f"<span>{escape(size)} bytes</span>", page)
        self.assertIn(f"<span>Modified {escape(modified)}</span>", page)
        self.assertIn(
            f"onclick=\"location.href='/law/imports/{escaped_filename}'\"",
            page,
        )
        self.assertIn(
            f'<form method="POST" action="/law/imports/{escaped_filename}/delete"',
            page,
        )
        self.assertIn(
            "Delete this saved raw import? This will not delete any structured case reviews already created from it.",
            page,
        )
        self.assertIn('aria-label="Delete import" title="Delete import"', page)
        self.assertNotIn('<tag id="importInjected">', page)
        self.assertNotIn('<b id="sizeInjected">', page)
        self.assertNotIn('<svg id="modifiedInjected">', page)
        self.assertEqual(2, page.count("</script>"))

    def test_import_deleted_banner_and_loader_failure_empty_state(self):
        page = self._get_imports([], "?deleted=1")
        self.assertIn("Saved import deleted.", page)
        self.assertIn("Structured case reviews were not changed.", page)

        with mock.patch.object(
            dlms._law_service,
            "list_law_raw_imports",
            side_effect=OSError("catalog unavailable"),
        ), mock.patch("builtins.print") as printer:
            failed = self.client.get("/law/imports")

        self.assertEqual(200, failed.status_code)
        failed_page = failed.get_data(as_text=True)
        self.assertIn('<span class="law-count-pill">0 saved</span>', failed_page)
        self.assertIn("No saved imports yet", failed_page)
        self.assertIn(
            mock.call("[LAW IMPORTS ERROR] Failed loading saved imports: catalog unavailable"),
            printer.call_args_list,
        )

    def test_case_catalog_empty_state_navigation_and_actions(self):
        page = self._get_cases({"cases": []})

        self.assert_catalog_shell(page, "My Case Reviews")
        self.assertIn('<span class="law-count-pill">0 saved</span>', page)
        self.assertIn("No case reviews yet", page)
        self.assertIn("Create a case review from a saved import", page)
        self.assertNotIn('class="law-record-row"', page)
        self.assertIn("location.href='/law/imports'", page)
        self.assertIn("location.href='/law/import'", page)
        self.assertIn("location.href='/law'", page)

    def test_case_catalog_sorts_and_escapes_displayed_metadata_and_actions(self):
        hostile = 'Case & <img id="caseInjected"> "quoted" \'single\' </script> \u2028\u2029'
        older = {
            "id": "older-case",
            "title": "Older Case",
            "course": "",
            "created_at": "2026-01-01T00:00:00",
            "source_import": "older.txt",
        }
        newer = {
            "id": hostile,
            "title": hostile,
            "course": '<b id="courseInjected">Torts</b>',
            "created_at": '<svg id="createdInjected">2026-09-07</svg>',
            "source_import": '<a id="sourceInjected">raw.txt</a>',
            "status": "draft-hidden-status",
            "description": "hidden-description",
            "file": "hidden-case-path.json",
        }
        page = self._get_cases({"cases": [older, newer]})
        escaped_hostile = str(escape(hostile))

        self.assertIn('<span class="law-count-pill">2 saved</span>', page)
        self.assertLess(page.index(escaped_hostile), page.index("Older Case"))
        self.assertIn(f"<h3>{escaped_hostile}</h3>", page)
        self.assertIn(f"<span>{escape(newer['course'])}</span>", page)
        self.assertIn(f"<span>Created {escape(newer['created_at'])}</span>", page)
        self.assertIn(f"Source: {escape(newer['source_import'])}", page)
        self.assertIn("<span>Uncategorized</span>", page)
        self.assertIn(
            f"onclick=\"location.href='/law/cases/{escaped_hostile}'\"",
            page,
        )
        self.assertIn(
            f'<form method="POST" action="/law/cases/{escaped_hostile}/delete"',
            page,
        )
        self.assertIn(
            "Delete this Law Case Review? This will remove the saved case review JSON file, but it will not delete the original raw import.",
            page,
        )
        self.assertIn(
            'aria-label="Delete case review" title="Delete case review"', page
        )
        for raw_markup in (
            '<img id="caseInjected">',
            '<b id="courseInjected">',
            '<svg id="createdInjected">',
            '<a id="sourceInjected">',
        ):
            self.assertNotIn(raw_markup, page)
        for unused_value in (
            "draft-hidden-status",
            "hidden-description",
            "hidden-case-path.json",
        ):
            self.assertNotIn(unused_value, page)
        self.assertEqual(2, page.count("</script>"))

    def test_case_deleted_banner_and_missing_cases_default(self):
        page = self._get_cases({}, "?deleted=yes")

        self.assertIn('<span class="law-count-pill">0 saved</span>', page)
        self.assertIn("Case review deleted.", page)
        self.assertIn("The original raw import was not changed.", page)

    def test_catalogs_do_not_render_or_consume_flashed_messages(self):
        message = 'Law catalog flash <b id="lawCatalogFlashInjected"> & pending'
        with self.client.session_transaction() as session:
            session["_flashes"] = [("success", message)]

        imports_page = self._get_imports([])
        cases_page = self._get_cases({"cases": []})

        self.assertNotIn(message, imports_page)
        self.assertNotIn(message, cases_page)
        self.assertNotIn("lawCatalogFlashInjected", imports_page)
        self.assertNotIn("lawCatalogFlashInjected", cases_page)
        with self.client.session_transaction() as session:
            self.assertEqual([("success", message)], session.get("_flashes"))

    def test_inline_javascript_is_static_and_shared_csrf_runtime_is_preserved(self):
        imports_page = self._get_imports([])
        cases_page = self._get_cases({"cases": []})

        for page in (imports_page, cases_page):
            with self.subTest(title=page.split("<title>", 1)[1].split("</title>", 1)[0]):
                inline_script = page.split("<script>", 1)[1].split("</script>", 1)[0]
                self.assertNotIn("{{", inline_script)
                self.assertIn(
                    'confirm("Shut down DLMS? You will need to restart it manually.")',
                    inline_script,
                )
                self.assertIn('fetch("/api/shutdown", { method: "POST" })', inline_script)
                self.assertIn("sidebar.classList.toggle(\"open\")", inline_script)
                self.assertIn("DLMS is shutting down.", inline_script)
                self.assertIn("Failed to shut down DLMS.", inline_script)

    def test_import_route_uses_external_template_with_unchanged_context(self):
        imports = [{"filename": "packet.txt", "size": 42, "modified": "today"}]
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Portal"
        ), mock.patch.object(
            dlms._law_service, "list_law_raw_imports", return_value=imports
        ), mock.patch.object(
            dlms, "render_template", return_value="rendered"
        ) as renderer:
            response = self.client.get("/law/imports")

        self.assertEqual(200, response.status_code)
        self.assertEqual("rendered", response.get_data(as_text=True))
        renderer.assert_called_once_with(
            "law/imports.html",
            portal_title="Law Portal",
            imports=imports,
        )
        self.assertTrue((Path(dlms.TEMPLATE_ROOT) / "law" / "imports.html").is_file())

    def test_case_route_uses_external_template_with_sorted_unchanged_context(self):
        older = {"id": "older", "created_at": "2026-01-01"}
        newer = {"id": "newer", "created_at": "2026-09-07"}
        registry = {"cases": [older, newer]}
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Portal"
        ), mock.patch.object(
            dlms, "load_law_registry", return_value=registry
        ), mock.patch.object(
            dlms, "render_template", return_value="rendered"
        ) as renderer:
            response = self.client.get("/law/cases")

        self.assertEqual(200, response.status_code)
        self.assertEqual("rendered", response.get_data(as_text=True))
        renderer.assert_called_once_with(
            "law/cases.html",
            portal_title="Law Portal",
            cases=[newer, older],
        )
        self.assertTrue((Path(dlms.TEMPLATE_ROOT) / "law" / "cases.html").is_file())


if __name__ == "__main__":
    unittest.main()
