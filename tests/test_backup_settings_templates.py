"""Characterization coverage for Backup & Restore settings views."""

import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from markupsafe import escape

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import maintenance as maintenance_routes
from tests.csrf_test_utils import csrf_headers


class BackupSettingsTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-backup-template-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.client = dlms.app.test_client()
        self.backup_folder = mock.patch.object(dlms, "BACKUP_FOLDER", str(self.backups))
        self.backup_folder.start()
        self.addCleanup(self.backup_folder.stop)

    @staticmethod
    def _assert_settings_shell(page):
        assert 'class="dashboard-shell"' in page
        assert 'id="dashboardSidebar"' in page
        assert 'class="dashboard-menu-button"' in page
        assert 'aria-controls="dashboardSidebar"' in page
        assert '<script src="/static/nav-normalize.js"></script>' in page

    def _post_stage(self, *, stage_result=None, stage_error=None, token="a" * 32):
        stage_dir = self.root / "restore-stage" / token

        def create_stage(path):
            Path(path).mkdir(parents=True)

        if stage_error is not None:
            stage_patch = mock.patch.object(
                dlms, "_stage_dlms_backup", side_effect=stage_error
            )
        else:
            stage_patch = mock.patch.object(
                dlms, "_stage_dlms_backup", return_value=stage_result
            )
        with mock.patch.object(dlms.secrets, "token_hex", return_value=token), \
             mock.patch.object(dlms, "_restore_staging_dir", return_value=str(stage_dir)), \
             mock.patch.object(
                 dlms._backup_service,
                 "create_backup_restore_stage",
                 side_effect=create_stage,
             ), \
             stage_patch:
            return self.client.post(
                "/settings/backup/restore/stage",
                data={"backup_file": (io.BytesIO(b"PK fake backup"), "backup.zip")},
                headers=csrf_headers(self.client, "/settings/backup"),
            )

    def test_get_renders_forms_recent_backups_banners_and_escaped_filenames(self):
        names = [
            'z-<img onerror="attack">-&-\'.zip',
            "y-safety.zip",
            "x-safety.zip",
            "w-safety.zip",
            "v-safety.zip",
            "a-sixth-is-hidden.zip",
        ]
        for index, name in enumerate(names):
            path = self.backups / name
            path.write_bytes(b"x" * (index + 1))
            os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))

        with mock.patch.object(
            maintenance_routes,
            "render_template",
            wraps=maintenance_routes.render_template,
        ) as render_template:
            response = self.client.get(
                "/settings/backup?restore_error=not-zip&restore_cancelled=1"
            )
        page = response.get_data(as_text=True)

        self.assertEqual(200, response.status_code)
        render_template.assert_called_once()
        self.assertEqual(("settings/backup.html",), render_template.call_args.args)
        self.assertIn("recent_backups", render_template.call_args.kwargs)
        self._assert_settings_shell(page)
        self.assertIn("SETTINGS / BACKUP &amp; RESTORE", page)
        self.assertIn(
            '<form method="POST" action="/settings/backup/create">', page
        )
        self.assertIn(
            '<form method="POST" action="/settings/backup/restore/stage" enctype="multipart/form-data">',
            page,
        )
        self.assertIn(
            '<input id="backupFile" class="settings-file-input" type="file" name="backup_file" accept=".zip,application/zip" required>',
            page,
        )
        self.assertIn("Restore file not accepted", page)
        self.assertIn("Restore cancelled", page)
        self.assertIn("No DLMS data was changed.", page)
        self.assertIn(str(escape(names[0])), page)
        self.assertNotIn(names[0], page)
        for name in names[1:5]:
            self.assertIn(name, page)
        self.assertNotIn(names[5], page)
        self.assertIn("/settings/reset-remove", page)

        plain = self.client.get("/settings/backup").get_data(as_text=True)
        self.assertNotIn("Restore file not accepted", plain)
        self.assertNotIn("Restore cancelled", plain)

    def test_backup_download_success_and_failure_view_keep_existing_contracts(self):
        archive = self.backups / "DLMS-backup.zip"
        archive.write_bytes(b"portable backup")
        with mock.patch.object(
            dlms, "_create_dlms_backup", return_value=(str(archive), {})
        ):
            success = self.client.post(
                "/settings/backup/create",
                headers=csrf_headers(self.client, "/settings/backup"),
            )
        self.assertEqual(200, success.status_code)
        self.assertEqual(b"portable backup", success.data)
        self.assertIn("attachment", success.headers["Content-Disposition"])
        self.assertIn("DLMS-backup.zip", success.headers["Content-Disposition"])

        with mock.patch.object(
            dlms, "_create_dlms_backup", side_effect=OSError("private path detail")
        ), mock.patch.object(
            maintenance_routes,
            "render_template",
            wraps=maintenance_routes.render_template,
        ) as render_template:
            failure = self.client.post(
                "/settings/backup/create",
                headers=csrf_headers(self.client, "/settings/backup"),
            )
        page = failure.get_data(as_text=True)
        self.assertEqual(500, failure.status_code)
        self.assertEqual(
            mock.call(
                "settings/backup-failed.html",
                error="DLMS could not create the backup. Check the local application log for details.",
            ),
            render_template.call_args,
        )
        self._assert_settings_shell(page)
        self.assertIn("Backup failed", page)
        self.assertIn("DLMS did not modify your existing data.", page)
        self.assertIn(
            "DLMS could not create the backup. Check the local application log for details.",
            page,
        )
        self.assertNotIn("private path detail", page)
        self.assertIn("location.href='/settings/backup'", page)

    def test_stage_redirects_and_validation_failure_message_are_unchanged(self):
        no_file = self.client.post(
            "/settings/backup/restore/stage",
            headers=csrf_headers(self.client, "/settings/backup"),
        )
        wrong_type = self.client.post(
            "/settings/backup/restore/stage",
            data={"backup_file": (io.BytesIO(b"text"), "backup.txt")},
            headers=csrf_headers(self.client, "/settings/backup"),
        )
        self.assertEqual(302, no_file.status_code)
        self.assertEqual(
            "/settings/backup?restore_error=no-file", no_file.headers["Location"]
        )
        self.assertEqual(302, wrong_type.status_code)
        self.assertEqual(
            "/settings/backup?restore_error=not-zip", wrong_type.headers["Location"]
        )

        with mock.patch.object(
            maintenance_routes,
            "render_template",
            wraps=maintenance_routes.render_template,
        ) as render_template:
            failure = self._post_stage(
                stage_error=ValueError("private archive detail")
            )
        page = failure.get_data(as_text=True)
        self.assertEqual(400, failure.status_code)
        self.assertEqual(
            mock.call(
                "settings/restore-validation-failed.html",
                error="The backup failed validation and was not accepted. Check the local DLMS log for details.",
            ),
            render_template.call_args,
        )
        self._assert_settings_shell(page)
        self.assertIn("Backup rejected", page)
        self.assertIn("No DLMS data was changed.", page)
        self.assertIn(
            "The backup failed validation and was not accepted. Check the local DLMS log for details.",
            page,
        )
        self.assertNotIn("private archive detail", page)
        self.assertIn("location.href='/settings/backup'", page)

    def test_restore_confirmation_preserves_metadata_forms_summary_and_warning(self):
        attack = '<img src=x onerror="attack"> & \'quoted\''
        manifest = {
            "created_at": f"Created {attack}",
            "dlms_version": f"Version {attack}",
            "summary": {
                "quizzes": f"7 {attack}",
                "attempts": 8,
                "content_packs": 9,
                "pdf_question_banks": 10,
                "pdf_terminology_banks": 11,
            },
        }
        report = {
            "manifest": manifest,
            "file_count": f"12 {attack}",
            "uncompressed_bytes": 1572864,
        }
        semantic = {"portal_config": {"status": "normalized"}}
        token = "b" * 32

        with mock.patch.object(
            maintenance_routes,
            "render_template",
            wraps=maintenance_routes.render_template,
        ) as render_template:
            response = self._post_stage(stage_result=(report, semantic), token=token)
        page = response.get_data(as_text=True)

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            mock.call(
                "settings/restore-confirm.html",
                manifest=manifest,
                report=report,
                semantic_validation=semantic,
                summary=manifest["summary"],
                token=token,
            ),
            render_template.call_args,
        )
        self._assert_settings_shell(page)
        self.assertIn("Review backup before restore", page)
        self.assertIn("Nothing has been restored yet.", page)
        self.assertIn(f"Created {escape(attack)}", page)
        self.assertIn(f"Version {escape(attack)}", page)
        self.assertIn(f"12 {escape(attack)}", page)
        self.assertIn(f"7 {escape(attack)} quizzes", page)
        self.assertNotIn(attack, page)
        self.assertIn("Uncompressed data:</strong> 1.5 MB", page)
        self.assertIn(
            "7 &lt;img src=x onerror=&#34;attack&#34;&gt; &amp; &#39;quoted&#39; quizzes · 8 attempts · 9 Content Packs · 10 question banks · 11 terminology banks",
            page,
        )
        self.assertIn("Custom AI URL will be cleared", page)
        self.assertIn("Automatic safety backup", page)
        self.assertEqual(
            2,
            page.count(
                f'<form method="POST" action="/settings/backup/restore/cancel/{token}">'
            ),
        )
        self.assertIn(
            f'<form method="POST" action="/settings/backup/restore/confirm/{token}">',
            page,
        )
        self.assertNotIn('type="hidden"', page)

        report["manifest"] = dict(manifest, summary={})
        without_warning = self._post_stage(
            stage_result=(report, {"portal_config": {"status": "valid"}}),
            token="c" * 32,
        ).get_data(as_text=True)
        self.assertNotIn("Custom AI URL will be cleared", without_warning)
        self.assertIn("0 quizzes · 0 attempts · 0 Content Packs", without_warning)

    def test_restore_complete_escapes_safety_name_and_conditions_cleanup_message(self):
        safety_name = '<safety onmouseover="attack">-&-\'.zip'
        with mock.patch.object(
            dlms,
            "_complete_staged_restore",
            return_value={
                "safety_path": str(self.root / safety_name),
                "cleanup_pending": True,
            },
        ), mock.patch.object(
            maintenance_routes,
            "render_template",
            wraps=maintenance_routes.render_template,
        ) as render_template:
            response = self.client.post(
                "/settings/backup/restore/confirm/" + "d" * 32,
                headers=csrf_headers(self.client, "/settings/backup"),
            )
        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            mock.call(
                "settings/restore-complete.html",
                safety_name=safety_name,
                cleanup_pending=True,
            ),
            render_template.call_args,
        )
        self._assert_settings_shell(page)
        self.assertIn("Restore complete", page)
        self.assertIn(str(escape(safety_name)), page)
        self.assertNotIn(safety_name, page)
        self.assertIn("Pre-restore safety backup preserved", page)
        self.assertIn("Cleanup will finish automatically", page)
        self.assertIn("location.href='/'", page)
        self.assertIn("location.href='/settings/backup'", page)

        with mock.patch.object(
            dlms,
            "_complete_staged_restore",
            return_value={"safety_path": "/tmp/safety.zip", "cleanup_pending": False},
        ):
            without_cleanup = self.client.post(
                "/settings/backup/restore/confirm/" + "e" * 32,
                headers=csrf_headers(self.client, "/settings/backup"),
            ).get_data(as_text=True)
        self.assertNotIn("Cleanup will finish automatically", without_cleanup)

    def test_restore_failure_escapes_public_errors_and_hides_internal_errors(self):
        public_error = 'Restore rejected <script>attack()</script> & "quoted"'
        with mock.patch.object(
            dlms,
            "_complete_staged_restore",
            side_effect=dlms.RestoreFutureSchemaError(public_error),
        ), mock.patch.object(
            maintenance_routes,
            "render_template",
            wraps=maintenance_routes.render_template,
        ) as render_template:
            public = self.client.post(
                "/settings/backup/restore/confirm/" + "f" * 32,
                headers=csrf_headers(self.client, "/settings/backup"),
            )
        public_page = public.get_data(as_text=True)
        self.assertEqual(400, public.status_code)
        self.assertEqual(
            mock.call("settings/restore-failed.html", error=public_error),
            render_template.call_args,
        )
        self._assert_settings_shell(public_page)
        self.assertIn("Restore failed", public_page)
        self.assertIn(str(escape(public_error)), public_page)
        self.assertNotIn(public_error, public_page)
        self.assertIn(
            "If a pre-restore backup was created, it remains in the DLMS backups folder.",
            public_page,
        )

        ownership_error = dlms.DataRootOwnershipError(
            'DLMS data root "/tmp/<unsafe>&" is not verified'
        )
        with mock.patch.object(
            dlms, "_complete_staged_restore", side_effect=ownership_error
        ):
            ownership = self.client.post(
                "/settings/backup/restore/confirm/" + "0" * 32,
                headers=csrf_headers(self.client, "/settings/backup"),
            )
        ownership_page = ownership.get_data(as_text=True)
        self.assertEqual(409, ownership.status_code)
        self.assertIn(str(escape(str(ownership_error))), ownership_page)
        self.assertNotIn(str(ownership_error), ownership_page)

        with mock.patch.object(
            dlms,
            "_complete_staged_restore",
            side_effect=OSError("private database path and journal detail"),
        ):
            internal = self.client.post(
                "/settings/backup/restore/confirm/" + "1" * 32,
                headers=csrf_headers(self.client, "/settings/backup"),
            )
        internal_page = internal.get_data(as_text=True)
        self.assertEqual(500, internal.status_code)
        self.assertIn(
            "DLMS could not complete the restore. Existing data was preserved or rolled back. Check the local application log for details.",
            internal_page,
        )
        self.assertNotIn("private database path and journal detail", internal_page)

    def test_legacy_backup_urls_and_cancel_redirect_remain_available(self):
        legacy_page = self.client.get("/settings/data")
        self.assertEqual(302, legacy_page.status_code)
        self.assertEqual("/settings/backup", legacy_page.headers["Location"])

        with mock.patch.object(
            dlms, "_cancel_validated_restore_stage", return_value="missing"
        ):
            cancelled = self.client.post(
                "/settings/backup/restore/cancel/" + "2" * 32,
                headers=csrf_headers(self.client, "/settings/backup"),
            )
        self.assertEqual(302, cancelled.status_code)
        self.assertEqual(
            "/settings/backup?restore_cancelled=1", cancelled.headers["Location"]
        )

    def test_all_backup_workflow_templates_exist_under_template_root(self):
        for name in (
            "backup.html",
            "backup-failed.html",
            "restore-validation-failed.html",
            "restore-confirm.html",
            "restore-complete.html",
            "restore-failed.html",
        ):
            with self.subTest(name=name):
                self.assertTrue((Path(dlms.TEMPLATE_ROOT) / "settings" / name).is_file())


if __name__ == "__main__":
    unittest.main()
