"""Characterization coverage for the Law saved-import detail view."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from markupsafe import escape

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import law as law_routes


class LawImportDetailTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()
        self.portal_title_patcher = mock.patch.object(
            dlms, "get_portal_title", return_value="Law Detail Portal"
        )
        self.content_packs_patcher = mock.patch.object(
            dlms, "discover_content_packs", return_value={}
        )
        self.portal_title_patcher.start()
        self.content_packs_patcher.start()
        self.addCleanup(self.content_packs_patcher.stop)
        self.addCleanup(self.portal_title_patcher.stop)

    def _get(
        self,
        requested_name="nested/packet.txt",
        *,
        safe_name="nested_packet.txt",
        raw_packet="",
        parsed_sections=None,
        query="",
        size=42,
        modified="2026-09-07 12:34:56",
    ):
        import_path = dlms.os.path.join(dlms.LAW_IMPORTS_FOLDER, safe_name)
        parsed_sections = [] if parsed_sections is None else parsed_sections
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Detail Portal"
        ) as title_loader, mock.patch.object(
            dlms, "safe_law_import_filename", return_value=safe_name
        ) as filename_validator, mock.patch.object(
            dlms.os.path, "exists", return_value=True
        ) as exists, mock.patch.object(
            dlms.os.path, "isfile", return_value=True
        ) as isfile, mock.patch.object(
            dlms._law_service, "load_law_raw_packet", return_value=raw_packet
        ) as loader, mock.patch.object(
            dlms.os, "stat", return_value=SimpleNamespace(st_mtime=123.0, st_size=size)
        ) as stat_file, mock.patch.object(
            dlms, "parse_law_packet_sections", return_value=parsed_sections
        ) as parser, mock.patch.object(dlms, "datetime") as datetime_mock:
            datetime_mock.fromtimestamp.return_value.strftime.return_value = modified
            response = self.client.get(f"/law/imports/{requested_name}{query}")

        self.assertEqual(200, response.status_code)
        title_loader.assert_called_once_with()
        filename_validator.assert_called_once_with(requested_name)
        exists.assert_called_once_with(import_path)
        self.assertIn(mock.call(import_path), isfile.call_args_list)
        loader.assert_called_once_with(import_path, open_file=open)
        self.assertGreaterEqual(stat_file.call_count, 2)
        stat_file.assert_has_calls([mock.call(import_path), mock.call(import_path)])
        datetime_mock.fromtimestamp.assert_called_once_with(123.0)
        datetime_mock.fromtimestamp.return_value.strftime.assert_called_once_with(
            "%Y-%m-%d %H:%M:%S"
        )
        parser.assert_called_once_with(raw_packet)
        return response.get_data(as_text=True)

    def assert_detail_shell(self, page):
        self.assertIn("<title>View Law Import - DLMS</title>", page)
        self.assertIn("<h1>View Law Import</h1>", page)
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
        self.assertIn('<textarea class="law-raw-packet" readonly rows="24">', page)
        self.assertIn("location.href='/law/imports'", page)
        self.assertIn("location.href='/law/cases'", page)
        self.assertIn("location.href='/law/import'", page)
        self.assertIn('<script src="/static/nav-normalize.js"></script>', page)

    def test_empty_packet_metadata_warning_and_absent_create_form(self):
        page = self._get(raw_packet="", size=0)

        self.assert_detail_shell(page)
        self.assertIn("<h2>nested_packet.txt</h2>", page)
        self.assertIn("<span>Lines</span><strong>0</strong>", page)
        self.assertIn("<span>Characters</span><strong>0</strong>", page)
        self.assertIn("<span>Size</span><strong>0 bytes</strong>", page)
        self.assertIn(
            '<strong class="law-detail-date">2026-09-07 12:34:56</strong>', page
        )
        self.assertIn("No recognized Law Study headings found.", page)
        self.assertIn("Expected headings include Case Brief", page)
        self.assertNotIn('class="law-detail-primary-form"', page)
        self.assertIn(
            '<textarea class="law-raw-packet" readonly rows="24"></textarea>', page
        )

    def test_parser_preview_form_contract_pluralization_and_escaping(self):
        filename = 'packet & <name id="filenameInjected"> "quoted" \'single\'.txt'
        raw_packet = (
            'Raw & <b id="rawInjected">text</b> </textarea>'
            '<script id="rawScriptInjected">bad()</script> \u2028\u2029'
        )
        title = '1. Case & <img id="sectionInjected"> </script> \u2028\u2029'
        sections = [
            {"title": title, "line_count": '<i id="lineInjected">2</i>', "char_count": 17},
            {"title": "4. Rule Flashcards", "line_count": 3, "char_count": '<u id="charInjected">9</u>'},
        ]
        page = self._get(
            requested_name="request.txt",
            safe_name=filename,
            raw_packet=raw_packet,
            parsed_sections=sections,
            size=123,
        )
        escaped_filename = str(escape(filename))

        self.assertIn(f"<h2>{escaped_filename}</h2>", page)
        self.assertIn(f"<h3>{escape(title)}</h3>", page)
        self.assertIn(f"<p>{escape(sections[0]['line_count'])} lines · 17 characters</p>", page)
        self.assertIn(f"<p>3 lines · {escape(sections[1]['char_count'])} characters</p>", page)
        self.assertIn("DLMS found 2 recognized sections.", page)
        self.assertIn(
            f'<form method="POST" action="/law/imports/{escaped_filename}/create_case" '
            'class="law-detail-primary-form">',
            page,
        )
        self.assertIn(
            "onclick=\"return confirm('Create a structured Law Case Review from this import?');\"",
            page,
        )
        self.assertIn("Create Case Review From Import", page)
        self.assertNotIn('name="csrf_token"', page)
        self.assertIn(
            f'<textarea class="law-raw-packet" readonly rows="24">{escape(raw_packet)}</textarea>',
            page,
        )
        for raw_markup in (
            '<name id="filenameInjected">',
            '<b id="rawInjected">',
            '<script id="rawScriptInjected">',
            '<img id="sectionInjected">',
            '<i id="lineInjected">',
            '<u id="charInjected">',
        ):
            self.assertNotIn(raw_markup, page)
        self.assertEqual(2, page.count("</script>"))
        self.assertEqual(1, page.count("</textarea>"))

    def test_single_parser_section_uses_singular_summary(self):
        page = self._get(
            raw_packet="1. Case Brief\nFacts",
            parsed_sections=[
                {"title": "1. Case Brief", "line_count": 1, "char_count": 5}
            ],
        )

        self.assertIn("DLMS found 1 recognized section.", page)
        self.assertNotIn("1 recognized sections", page)

    def test_created_case_query_banner_and_flashes_are_request_scoped_as_before(self):
        message = 'Law detail flash <b id="lawDetailFlashInjected"> pending'
        with self.client.session_transaction() as session:
            session["_flashes"] = [("success", message)]

        page = self._get(query="?created_case=1")

        self.assertIn("Case review created.", page)
        self.assertIn("saved and added to the Law Study registry", page)
        self.assertNotIn(message, page)
        self.assertNotIn("lawDetailFlashInjected", page)
        with self.client.session_transaction() as session:
            self.assertEqual([("success", message)], session.get("_flashes"))

    def test_filename_validation_missing_file_and_read_failure_responses(self):
        with mock.patch.object(
            dlms, "safe_law_import_filename", return_value=""
        ) as validator, mock.patch.object(dlms.os.path, "exists") as exists:
            invalid = self.client.get("/law/imports/../../case.json")

        self.assertEqual(400, invalid.status_code)
        self.assertEqual("Invalid import filename", invalid.get_data(as_text=True))
        validator.assert_called_once_with("../../case.json")
        exists.assert_not_called()

        with mock.patch.object(
            dlms, "safe_law_import_filename", return_value="missing.txt"
        ), mock.patch.object(dlms.os.path, "exists", return_value=False), mock.patch.object(
            dlms.os.path, "isfile"
        ) as isfile:
            missing = self.client.get("/law/imports/missing.txt")

        self.assertEqual(404, missing.status_code)
        self.assertEqual("Saved import not found", missing.get_data(as_text=True))
        isfile.assert_not_called()

        with mock.patch.object(
            dlms, "safe_law_import_filename", return_value="folder.txt"
        ), mock.patch.object(dlms.os.path, "exists", return_value=True), mock.patch.object(
            dlms.os.path, "isfile", return_value=False
        ):
            non_file = self.client.get("/law/imports/folder.txt")

        self.assertEqual(404, non_file.status_code)
        self.assertEqual("Saved import not found", non_file.get_data(as_text=True))

        with mock.patch.object(
            dlms, "safe_law_import_filename", return_value="unreadable.txt"
        ), mock.patch.object(dlms.os.path, "exists", return_value=True), mock.patch.object(
            dlms.os.path, "isfile", return_value=True
        ), mock.patch.object(
            dlms._law_service,
            "load_law_raw_packet",
            side_effect=OSError("read blocked"),
        ), mock.patch("builtins.print") as printer:
            unreadable = self.client.get("/law/imports/unreadable.txt")

        self.assertEqual(500, unreadable.status_code)
        self.assertEqual("Failed to read saved import", unreadable.get_data(as_text=True))
        self.assertIn(
            mock.call("[LAW IMPORT ERROR] Failed reading saved import: read blocked"),
            printer.call_args_list,
        )

    def test_inline_javascript_is_static_and_shutdown_contract_is_preserved(self):
        page = self._get()
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

    def test_route_uses_external_template_with_unchanged_context(self):
        safe_name = "normalized_packet.txt"
        raw_packet = "1. Case Brief\nFacts"
        sections = [{"title": "1. Case Brief", "line_count": 1, "char_count": 5}]
        import_path = dlms.os.path.join(dlms.LAW_IMPORTS_FOLDER, safe_name)
        with mock.patch.object(
            dlms, "get_portal_title", return_value="Law Portal"
        ), mock.patch.object(
            dlms, "safe_law_import_filename", return_value=safe_name
        ), mock.patch.object(
            dlms.os.path, "exists", return_value=True
        ), mock.patch.object(
            dlms.os.path, "isfile", return_value=True
        ), mock.patch.object(
            dlms._law_service, "load_law_raw_packet", return_value=raw_packet
        ) as loader, mock.patch.object(
            dlms.os, "stat", return_value=SimpleNamespace(st_mtime=123.0, st_size=20)
        ), mock.patch.object(
            dlms, "parse_law_packet_sections", return_value=sections
        ), mock.patch.object(dlms, "datetime") as datetime_mock, mock.patch.object(
            law_routes, "render_template", return_value="rendered"
        ) as renderer:
            datetime_mock.fromtimestamp.return_value.strftime.return_value = (
                "2026-09-07 12:34:56"
            )
            response = self.client.get("/law/imports/request/path.txt")

        self.assertEqual(200, response.status_code)
        self.assertEqual("rendered", response.get_data(as_text=True))
        renderer.assert_called_once_with(
            "law/import-detail.html",
            portal_title="Law Portal",
            filename=safe_name,
            raw_packet=raw_packet,
            line_count=2,
            char_count=19,
            modified="2026-09-07 12:34:56",
            size=20,
            parsed_sections=sections,
        )
        self.assertTrue(
            (Path(dlms.TEMPLATE_ROOT) / "law" / "import-detail.html").is_file()
        )
        loader.assert_called_once_with(import_path, open_file=open)


if __name__ == "__main__":
    unittest.main()
