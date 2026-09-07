"""Characterization coverage for Content Pack catalog and detail views."""

import unittest
from pathlib import Path
from unittest import mock

from markupsafe import escape

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


class ContentPackCatalogTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    def _catalog(self, packs, *, folder=None):
        patches = [
            mock.patch.object(dlms, "content_pack_management_summary", return_value=packs),
            mock.patch.object(dlms, "discover_content_packs", return_value={}),
        ]
        if folder is not None:
            patches.append(mock.patch.object(dlms, "CONTENT_PACK_FOLDER", folder))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        response = self.client.get("/content-packs")
        self.assertEqual(200, response.status_code)
        return response.get_data(as_text=True)

    @staticmethod
    def _pack(**overrides):
        pack = {
            "folder": "DLMS_Study_sample",
            "id": "sample",
            "name": "Sample Pack",
            "version": "1.2.3",
            "description": "Sample description",
            "domain": "IT",
            "matching_count": 2,
            "image_count": 1,
            "mixed_count": 1,
            "dataset_count": 4,
            "file_count": 8,
            "size": "12 KB",
            "status": "Valid",
            "status_detail": "DLMS independent validation passed without warnings.",
            "protected": False,
            "generated_quizzes": 3,
            "warning_count": 0,
            "error_count": 0,
            "validation_report": {},
            "installed_at": "Sep 06, 2026 01:00 PM",
            "exportable": True,
        }
        pack.update(overrides)
        return pack

    @staticmethod
    def _report(**overrides):
        report = {
            "valid": True,
            "errors": [],
            "warnings": ["Review optional metadata."],
            "checks": [
                {"status": "PASS", "name": "Manifest", "detail": "Manifest accepted."},
                {"status": "INFO", "name": "Metadata", "detail": "Optional metadata absent."},
            ],
            "manifest": {
                "schema_version": 1,
                "id": "sample",
                "name": "Sample Pack",
                "version": "1.2.3",
                "description": "Sample description",
                "content_domain": "IT",
                "datasets": [{"id": "one"}, {"id": "two"}],
                "image_datasets": "legacy malformed value",
                "quiz_datasets": [{"id": "mixed"}],
            },
            "pack_id": "sample",
            "pack_name": "Sample Pack",
            "dataset_count": 3,
            "folder": "DLMS_Study_sample",
            "root": "/data/content_packs/DLMS_Study_sample",
            "file_count": 8,
            "size": "12 KB",
            "generated_quizzes": 3,
            "installed_at": "Sep 06, 2026 01:00 PM",
        }
        report.update(overrides)
        return report

    def _details(self, report, folder="DLMS_Study_sample"):
        with mock.patch.object(
            dlms, "_content_pack_folder_report", return_value=report
        ), mock.patch.object(dlms, "discover_content_packs", return_value={}):
            response = self.client.get(f"/content-packs/details/{folder}")
        self.assertEqual(200, response.status_code)
        return response.get_data(as_text=True)

    def test_routes_use_external_templates_and_preserve_context(self):
        packs = [self._pack()]
        with mock.patch.object(
            dlms, "content_pack_management_summary", return_value=packs
        ), mock.patch.object(
            dlms, "discover_content_packs", return_value={}
        ), mock.patch.object(
            dlms, "render_template", wraps=dlms.render_template
        ) as render_template:
            catalog = self.client.get("/content-packs")

        self.assertEqual(200, catalog.status_code)
        render_template.assert_called_once_with(
            "content_packs/index.html",
            packs=packs,
            pack_folder=dlms.CONTENT_PACK_FOLDER,
            medical_pack_installed=True,
        )
        self.assertTrue(
            (Path(dlms.TEMPLATE_ROOT) / "content_packs" / "index.html").is_file()
        )

        report = self._report()
        with mock.patch.object(
            dlms, "_content_pack_folder_report", return_value=report
        ), mock.patch.object(
            dlms, "discover_content_packs", return_value={}
        ), mock.patch.object(
            dlms, "render_template", wraps=dlms.render_template
        ) as render_template:
            detail = self.client.get("/content-packs/details/DLMS_Study_sample")

        self.assertEqual(200, detail.status_code)
        render_template.assert_called_once_with(
            "content_packs/detail.html",
            report=report,
            manifest=report["manifest"],
            matching=2,
            image=0,
            mixed=1,
            medical_pack_installed=True,
        )
        self.assertTrue(
            (Path(dlms.TEMPLATE_ROOT) / "content_packs" / "detail.html").is_file()
        )

    def test_catalog_empty_state_forms_navigation_flash_and_accessibility(self):
        hostile_folder = '/packs/<script>alert("folder")</script>&'
        hostile_flash = 'Notice <img src=x onerror="attack"> & unsafe-looking'
        with self.client.session_transaction() as session:
            session["_flashes"] = [("error", hostile_flash)]

        page = self._catalog([], folder=hostile_folder)

        self.assertIn("<title>Content Packs - DLMS</title>", page)
        self.assertIn("No content packs installed", page)
        self.assertIn("0 installed folders", page)
        self.assertIn(str(escape(hostile_folder)), page)
        self.assertNotIn(hostile_folder, page)
        self.assertIn(str(escape(hostile_flash)), page)
        self.assertNotIn(hostile_flash, page)
        self.assertIn(
            '<form method="POST" action="/content-packs/import" enctype="multipart/form-data" class="content-pack-upload-form">',
            page,
        )
        self.assertIn(
            '<input type="file" name="pack_zip" accept=".zip,application/zip" required>',
            page,
        )
        self.assertIn(
            '<form method="POST" action="/content-packs/delete" id="deletePackForm">',
            page,
        )
        self.assertIn('name="folder" id="deletePackFolder"', page)
        self.assertIn('name="confirm_delete" value="yes" required', page)
        self.assertIn(
            'role="dialog" aria-modal="true" aria-labelledby="deletePackTitle"',
            page,
        )
        self.assertIn('aria-label="Toggle navigation"', page)
        self.assertIn('aria-controls="dashboardSidebar"', page)
        self.assertIn('aria-expanded="false"', page)
        self.assertIn(
            'class="dashboard-nav-item active" href="/content-packs"', page
        )
        self.assertIn('href="/study-packs"', page)
        self.assertIn('href="/admin/image-editor"', page)
        self.assertIn('<script src="/static/nav-normalize.js"></script>', page)

    def test_catalog_listing_preserves_counts_badges_actions_and_safe_serialization(self):
        hostile = self._pack(
            folder='folder-</script>-\'&"',
            name='Name </script> \' & "quoted" \u2028\u2029',
            version="1<2",
            domain="Other & <Domain>",
            status="Valid with warnings",
            status_detail="Detail <svg onload=attack> & safe",
            warning_count=2,
            matching_count=2,
            image_count=3,
            mixed_count=4,
            dataset_count=9,
            size="6 < MB",
            file_count=5,
            generated_quizzes=7,
        )
        protected = self._pack(
            folder="protected-pack",
            name="Protected Pack",
            version="",
            domain="General",
            status="Invalid",
            status_detail="Blocking validation failure.",
            protected=True,
            exportable=False,
            matching_count=0,
            image_count=0,
            mixed_count=0,
            dataset_count=0,
            warning_count=0,
            error_count=1,
        )

        page = self._catalog([hostile, protected])

        self.assertIn("2 installed folders", page)
        for value in (
            hostile["name"], hostile["domain"], hostile["version"],
            hostile["folder"], hostile["status_detail"], hostile["size"],
        ):
            self.assertIn(str(escape(value)), page)
        self.assertEqual(2, page.count("</script>"))
        self.assertNotIn('<svg onload="attack">', page)
        self.assertIn("2 matching", page)
        self.assertIn("3 image", page)
        self.assertIn("4 mixed", page)
        self.assertIn("2 warnings", page)
        self.assertIn("1 error", page)
        self.assertIn("content-pack-status is-warning", page)
        self.assertIn("content-pack-status is-invalid", page)
        self.assertIn("content-pack-protected", page)
        self.assertIn('<span class="content-pack-action disabled">Delete</span>', page)
        self.assertIn('href="/content-packs/details/protected-pack"', page)
        self.assertNotIn('href="/content-packs/export/protected-pack"', page)
        self.assertIn("<span>—</span>", page)
        self.assertIn(
            r'openDeletePack("folder-\u003c/script\u003e-\u0027\u0026\"",', page
        )
        self.assertIn(
            r'"Name \u003c/script\u003e \u0027 \u0026 \"quoted\" \u2028\u2029")',
            page,
        )
        self.assertNotIn("onclick='openDeletePack(\"folder-</script>", page)

    def test_detail_page_preserves_metadata_counts_validation_and_escaping(self):
        manifest = {
            "schema_version": '1<schema>',
            "id": "hostile",
            "name": "Manifest Name",
            "version": '2<version> & "quoted"',
            "description": 'Description </script><img src=x onerror="attack"> & safe',
            "content_domain": "IT & <Operations>",
            "datasets": [{"id": "one"}, {"id": "two"}],
            "image_datasets": "not a list",
            "quiz_datasets": [{"id": "mixed"}],
        }
        report = self._report(
            manifest=manifest,
            pack_name='Pack </script> & "Name"',
            pack_id="pack-<id>&",
            folder='folder-<name>&"',
            size="15 < MiB",
            installed_at="Sep <06> & now",
            warnings=['Warning <img onerror="attack">'],
            checks=[{
                "status": 'PASS"><img src=x onerror="attack">',
                "name": "Check <name> & value",
                "detail": 'Detail </script> & "quoted"',
            }],
        )

        page = self._details(report)

        for value in (
            report["pack_name"], report["pack_id"], report["folder"],
            report["size"], report["installed_at"], manifest["content_domain"],
            manifest["version"], manifest["description"], manifest["schema_version"],
            report["warnings"][0], report["checks"][0]["status"],
            report["checks"][0]["name"], report["checks"][0]["detail"],
        ):
            self.assertIn(str(escape(value)), page)
        self.assertEqual(2, page.count("</script>"))
        self.assertNotIn('<img src=x onerror="attack">', page)
        self.assertIn("<strong>3</strong><small>2 matching · 0 image · 1 mixed</small>", page)
        self.assertIn(
            "<span>Warnings</span><strong>1</strong><small>0 blocking errors</small>",
            page,
        )
        self.assertIn("<h3>Warnings</h3>", page)
        self.assertNotIn("<h3>Blocking problems</h3>", page)
        self.assertIn("content-pack-status is-valid", page)
        self.assertIn(
            'href="/content-packs/export/folder-&lt;name&gt;&amp;&#34;"', page
        )
        self.assertIn('href="/content-packs">← Back to Content Packs</a>', page)
        self.assertIn(
            'class="dashboard-nav-item active" href="/content-packs"', page
        )
        self.assertIn('aria-label="Toggle navigation"', page)
        self.assertIn('aria-controls="dashboardSidebar"', page)

    def test_invalid_detail_hides_export_and_shows_errors_defaults_and_status(self):
        report = self._report(
            valid=False,
            errors=["Manifest is invalid."],
            warnings=[],
            checks=[],
            pack_id="",
            pack_name="Invalid Folder",
            manifest={
                "datasets": [],
                "image_datasets": [],
                "quiz_datasets": [],
            },
        )

        page = self._details(report)

        self.assertIn("No pack description provided.", page)
        self.assertIn("GENERAL", page)
        self.assertIn("Unavailable", page)
        self.assertIn("content-pack-status is-invalid", page)
        self.assertIn("<h3>Blocking problems</h3>", page)
        self.assertIn("Manifest is invalid.", page)
        self.assertIn("0 checks", page)
        self.assertNotIn("Export Study Pack ZIP", page)

    def test_detail_failure_redirects_without_exposing_exception(self):
        with mock.patch.object(
            dlms,
            "_content_pack_folder_report",
            side_effect=ValueError("private filesystem detail"),
        ):
            response = self.client.get("/content-packs/details/invalid")

        self.assertEqual(302, response.status_code)
        self.assertEqual("/content-packs", response.headers["Location"])
        with self.client.session_transaction() as session:
            flashes = session.get("_flashes", [])
        self.assertEqual(
            [("error", "Content Pack details are unavailable. Check the local DLMS log for details.")],
            flashes,
        )
        self.assertNotIn("private filesystem detail", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
