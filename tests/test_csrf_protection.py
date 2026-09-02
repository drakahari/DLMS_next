import io
import os
import re
import stat
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import app as dlms
from tests.csrf_test_utils import csrf_headers, csrf_token


class CsrfProtectionTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    def test_html_get_delivers_strict_session_token_and_read_only_get_works(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("dlms_csrf_token=", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_tokenless_and_invalid_posts_are_rejected(self):
        self.assertEqual(self.client.post("/api/theme", json={"theme": "dark"}).status_code, 400)
        self.assertEqual(
            self.client.post("/api/theme", json={"theme": "dark"}, headers={"X-CSRFToken": "invalid"}).status_code,
            400,
        )

    def test_guided_study_pack_zip_intake_requires_same_origin_csrf(self):
        self.assertEqual(
            self.client.post(
                "/study-packs/ai-builder/import",
                data={"pack_zip": (io.BytesIO(b"PK-test"), "pack.zip")},
                content_type="multipart/form-data",
            ).status_code,
            400,
        )
        headers = {"Origin": "https://attacker.example"}
        response = self.client.post(
            "/study-packs/ai-builder/import",
            data={
                "csrf_token": csrf_token(self.client, "/study-packs/ai-builder"),
                "pack_zip": (io.BytesIO(b"PK-test"), "pack.zip"),
            },
            headers=headers,
            content_type="multipart/form-data",
        )
        self.assertEqual(403, response.status_code)

    def test_valid_form_and_json_header_tokens_succeed(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            dlms, "PORTAL_CONFIG", os.path.join(directory, "portal.json")
        ), mock.patch.object(dlms, "load_portal_config", return_value={"title": "DLMS", "theme": "dark"}):
            form_token = csrf_token(self.client)
            form_response = self.client.post("/api/theme", data={"theme": "light", "csrf_token": form_token})
            self.assertEqual(form_response.status_code, 200)
            json_response = self.client.post(
                "/api/theme", json={"theme": "dark"}, headers=csrf_headers(self.client)
            )
            self.assertEqual(json_response.status_code, 200)

    def test_token_from_another_session_is_rejected(self):
        other_client = dlms.app.test_client()
        other_token = csrf_token(other_client)
        response = self.client.post("/api/theme", json={"theme": "dark"}, headers={"X-CSRFToken": other_token})
        self.assertEqual(response.status_code, 400)

    def test_cross_origin_is_rejected_even_with_valid_token(self):
        headers = csrf_headers(self.client)
        headers["Origin"] = "https://attacker.example"
        response = self.client.post("/api/theme", json={"theme": "dark"}, headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertIn("origin", response.get_json()["error"].lower())

    def test_same_origin_and_missing_source_headers_accept_valid_token(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            dlms, "PORTAL_CONFIG", os.path.join(directory, "portal.json")
        ), mock.patch.object(dlms, "load_portal_config", return_value={"title": "DLMS", "theme": "dark"}):
            headers = csrf_headers(self.client)
            headers["Origin"] = "http://localhost"
            self.assertEqual(self.client.post("/api/theme", json={"theme": "light"}, headers=headers).status_code, 200)
            self.assertEqual(
                self.client.post("/api/theme", json={"theme": "dark"}, headers=csrf_headers(self.client)).status_code,
                200,
            )

    def test_lan_host_same_origin_is_supported_without_weakening_checks(self):
        client = dlms.app.test_client()
        client.get("/", base_url="http://192.168.1.25:9001")
        token = client.get_cookie("dlms_csrf_token", domain="192.168.1.25").value
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            dlms, "PORTAL_CONFIG", os.path.join(directory, "portal.json")
        ), mock.patch.object(dlms, "load_portal_config", return_value={"title": "DLMS", "theme": "dark"}):
            response = client.post(
                "/api/theme", base_url="http://192.168.1.25:9001", json={"theme": "light"},
                headers={"X-CSRFToken": token, "Origin": "http://192.168.1.25:9001"},
            )
            self.assertEqual(response.status_code, 200)
            blocked = client.post(
                "/api/theme", base_url="http://192.168.1.25:9001", json={"theme": "dark"},
                headers={"X-CSRFToken": token, "Origin": "http://192.168.1.26:9001"},
            )
            self.assertEqual(blocked.status_code, 403)

    def test_wildcard_bind_uses_browser_facing_lan_origin_for_ai_builder_post(self):
        startup = dlms._dlms_parse_startup_options(
            ["--host", "0.0.0.0", "--no-browser"],
            environ={},
            desktop_available=False,
        )
        self.assertEqual("0.0.0.0", startup["host"])

        client = dlms.app.test_client()
        base_url = "http://192.168.1.245:9001"
        client.get("/study-packs/ai-builder", base_url=base_url)
        token = client.get_cookie("dlms_csrf_token", domain="192.168.1.245").value
        with dlms.app.test_request_context(
            "/study-packs/ai-builder",
            method="POST",
            base_url=base_url,
            headers={"Origin": base_url},
        ):
            self.assertEqual("192.168.1.245:9001", dlms.request.host)
            self.assertEqual("http://192.168.1.245:9001/", dlms.request.host_url)
            self.assertEqual(("http", "192.168.1.245", 9001), dlms._request_facing_origin())
            self.assertTrue(dlms._request_source_matches(base_url))

        config = {
            "ai_provider": "chatgpt",
            "study_pack_ai_prompt_template": dlms.DEFAULT_STUDY_CONTENT_PACK_PROMPT,
            "medical_study_pack_ai_addendum": dlms.DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM,
        }
        with mock.patch.object(dlms, "load_portal_config", return_value=config):
            response = client.post(
                "/study-packs/ai-builder",
                base_url=base_url,
                headers={"Origin": base_url, "Sec-Fetch-Site": "same-origin"},
                data={
                    "csrf_token": token,
                    "topic": "Network layers",
                    "domain": "IT / Cybersecurity",
                    "difficulty": "Intermediate",
                    "size": "Standard",
                    "image_count": "None",
                    "image_style": "Mixed",
                    "ai_provider": "chatgpt",
                    "include_matching": "on",
                },
            )
        self.assertEqual(200, response.status_code)
        self.assertIn("GENERATED PROMPT", response.get_data(as_text=True))

    def test_loopback_and_localhost_same_origin_ports_are_supported(self):
        for hostname in ("127.0.0.1", "localhost"):
            with self.subTest(hostname=hostname), tempfile.TemporaryDirectory() as directory, \
                 mock.patch.object(dlms, "PORTAL_CONFIG", os.path.join(directory, "portal.json")), \
                 mock.patch.object(dlms, "load_portal_config", return_value={"title":"DLMS","theme":"dark"}):
                client = dlms.app.test_client()
                base_url = f"http://{hostname}:9001"
                client.get("/", base_url=base_url)
                token = client.get_cookie("dlms_csrf_token", domain=hostname).value
                response = client.post(
                    "/api/theme",
                    base_url=base_url,
                    json={"theme":"light"},
                    headers={"X-CSRFToken":token, "Origin":base_url},
                )
                self.assertEqual(200, response.status_code)

    def test_same_host_wrong_port_and_different_host_are_rejected(self):
        client = dlms.app.test_client()
        base_url = "http://192.168.1.245:9001"
        client.get("/", base_url=base_url)
        token = client.get_cookie("dlms_csrf_token", domain="192.168.1.245").value
        for origin in (
            "http://192.168.1.245:9002",
            "http://192.168.1.246:9001",
            "https://192.168.1.245:9001",
        ):
            with self.subTest(origin=origin):
                response = client.post(
                    "/api/theme",
                    base_url=base_url,
                    json={"theme":"dark"},
                    headers={"X-CSRFToken":token, "Origin":origin},
                )
                self.assertEqual(403, response.status_code)
                self.assertIn("origin", response.get_json()["error"].lower())

    def test_null_origin_with_valid_session_token_uses_csrf_fallback(self):
        client = dlms.app.test_client()
        base_url = "http://192.168.1.245:9001"
        client.get("/", base_url=base_url)
        token = client.get_cookie("dlms_csrf_token", domain="192.168.1.245").value
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            dlms, "PORTAL_CONFIG", os.path.join(directory, "portal.json")
        ), mock.patch.object(
            dlms, "load_portal_config", return_value={"title":"DLMS", "theme":"dark"}
        ), redirect_stdout(output):
            response = client.post(
                "/api/theme",
                base_url=base_url,
                json={"theme":"light"},
                headers={
                    "X-CSRFToken":token,
                    "Origin":"null",
                    "Sec-Fetch-Site":"same-origin",
                },
            )
        self.assertEqual(200, response.status_code)
        self.assertIn("Indeterminate Origin 'null'", output.getvalue())

    def test_null_origin_still_requires_valid_session_csrf_token(self):
        client = dlms.app.test_client()
        base_url = "http://192.168.1.245:9001"
        client.get("/", base_url=base_url)
        missing = client.post(
            "/api/theme",
            base_url=base_url,
            json={"theme":"dark"},
            headers={"Origin":"null", "Sec-Fetch-Site":"same-origin"},
        )
        invalid = client.post(
            "/api/theme",
            base_url=base_url,
            json={"theme":"dark"},
            headers={
                "X-CSRFToken":"invalid",
                "Origin":"null",
                "Sec-Fetch-Site":"same-origin",
            },
        )
        self.assertEqual(400, missing.status_code)
        self.assertEqual(400, invalid.status_code)

    def test_null_origin_cross_site_or_mismatched_referer_is_rejected(self):
        client = dlms.app.test_client()
        base_url = "http://192.168.1.245:9001"
        client.get("/", base_url=base_url)
        token = client.get_cookie("dlms_csrf_token", domain="192.168.1.245").value
        cross_site = client.post(
            "/api/theme",
            base_url=base_url,
            json={"theme":"dark"},
            headers={
                "X-CSRFToken":token,
                "Origin":"null",
                "Sec-Fetch-Site":"cross-site",
            },
        )
        bad_referer = client.post(
            "/api/theme",
            base_url=base_url,
            json={"theme":"dark"},
            headers={
                "X-CSRFToken":token,
                "Origin":"null",
                "Referer":"https://attacker.example/private?secret=not-logged",
            },
        )
        self.assertEqual(403, cross_site.status_code)
        self.assertEqual(403, bad_referer.status_code)

    def test_invalid_origin_logging_is_sanitized_and_bounded(self):
        client = dlms.app.test_client()
        token = csrf_token(client)
        output = io.StringIO()
        invalid_origin = "not-an-origin-" + ("x" * 300)
        with redirect_stdout(output):
            response = client.post(
                "/api/theme",
                json={"theme":"dark"},
                headers={"X-CSRFToken":token, "Origin":invalid_origin},
            )
        logged = output.getvalue()
        self.assertEqual(403, response.status_code)
        self.assertIn("'not-an-origin-", logged)
        self.assertIn("…'", logged)
        self.assertNotIn("x" * 200, logged)

    def test_sec_fetch_cross_site_and_cross_origin_referer_are_rejected(self):
        token = csrf_token(self.client)
        cross_site = self.client.post(
            "/api/theme", json={"theme": "dark"},
            headers={"X-CSRFToken": token, "Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(cross_site.status_code, 403)
        bad_referer = self.client.post(
            "/api/theme", json={"theme": "dark"},
            headers={"X-CSRFToken": token, "Referer": "https://attacker.example/page"},
        )
        self.assertEqual(bad_referer.status_code, 403)

    def test_empty_body_fetch_with_header_token_reaches_handler(self):
        with mock.patch.object(dlms, "load_registry", return_value=[]):
            response = self.client.post("/admin/rebuild_all_quiz_html", headers=csrf_headers(self.client))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["rebuilt"], 0)

    def test_cross_origin_destructive_requests_never_reach_handlers(self):
        token = csrf_token(self.client)
        headers = {"X-CSRFToken": token, "Origin": "https://attacker.example"}
        with mock.patch.object(threading, "Timer") as timer:
            self.assertEqual(self.client.post("/api/shutdown", headers=headers).status_code, 403)
            timer.assert_not_called()
        with mock.patch.object(dlms, "_run_reset_with_backup") as reset:
            for route in ("/api/reset_quiz_library", "/api/reset_learning_intelligence", "/api/reset_source_content", "/api/reset_app_settings", "/api/reset_all_data"):
                self.assertEqual(self.client.post(route, headers=headers).status_code, 403)
            reset.assert_not_called()
        with mock.patch.object(dlms, "get_db") as get_db:
            self.assertEqual(self.client.post("/api/clear_db_history", headers=headers).status_code, 403)
            get_db.assert_not_called()

    def test_rebuild_is_post_only_and_valid_post_rebuilds(self):
        with mock.patch.object(dlms, "load_registry") as registry:
            self.assertEqual(self.client.get("/admin/rebuild_all_quiz_html").status_code, 405)
            registry.assert_not_called()
        with mock.patch.object(dlms, "load_registry", return_value=[{"id": 7}]), mock.patch.object(
            dlms, "rebuild_quiz_html_from_registry", return_value=True
        ) as rebuild:
            response = self.client.post("/admin/rebuild_all_quiz_html", headers=csrf_headers(self.client))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["rebuilt"], 1)
        rebuild.assert_called_once_with(7)

    def test_multipart_pdf_backup_and_content_pack_requests_pass_csrf_layer(self):
        token = csrf_token(self.client)
        pages = [{"page": 1, "lines": ["1. Which?", "A. One", "B. Two", "Correct Answer: A"]}]
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            dlms, "PDF_IMPORT_DRAFT_FOLDER", directory
        ), mock.patch.object(dlms, "_pdf_extract_pages", return_value=pages), mock.patch.object(
            dlms, "_save_pdf_import_draft"
        ) as save_draft:
            pdf_response = self.client.post(
                "/pdf-import/analyze",
                data={
                    "csrf_token": token, "rights_ok": "1", "pdf_content_type": "question_bank",
                    "pdf_file": (io.BytesIO(b"%PDF-test"), "notes.pdf"),
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(pdf_response.status_code, 302)
            self.assertIn("/pdf-import/review/", pdf_response.headers["Location"])
            save_draft.assert_called_once()

        report = {
            "manifest": {
                "schema_version": dlms.DLMS_BACKUP_SCHEMA_VERSION,
                "kind": "dlms-portable-backup",
                "file_count": 1,
                "created_at": "2026-08-29",
                "dlms_version": "3.0.1",
                "summary": {},
            },
            "file_count": 1, "uncompressed_bytes": 100, "members": [],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            dlms, "BACKUP_RESTORE_STAGING_FOLDER", directory
        ), mock.patch.object(dlms, "_validate_dlms_backup", return_value=report), mock.patch.object(
            dlms, "_extract_validated_backup"
        ), mock.patch.object(
            dlms, "_validate_staged_backup_semantics", return_value={"status": "valid"}
        ):
            backup_response = self.client.post(
                "/settings/backup/restore/stage",
                data={"csrf_token": token, "backup_file": (io.BytesIO(b"PK-test"), "backup.zip")},
                content_type="multipart/form-data",
            )
            self.assertEqual(backup_response.status_code, 200)
            self.assertIn("Valid DLMS Backup", backup_response.get_data(as_text=True))

        inspection = {"root_name": "sample-pack", "file_count": 2, "uncompressed_bytes": 100}
        report = {"valid": True, "errors": [], "warnings": [], "checks": [], "pack_id": "sample", "pack_name": "Sample", "dataset_count": 1}
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            dlms, "CONTENT_PACK_STAGING_FOLDER", directory
        ), mock.patch.object(dlms.zipfile, "is_zipfile", return_value=True), mock.patch.object(
            dlms, "_inspect_content_pack_zip", return_value=inspection
        ), mock.patch.object(dlms, "_extract_content_pack_zip"), mock.patch.object(
            dlms, "_safe_pack_child", return_value=os.path.join(directory, "sample-pack")
        ), mock.patch.object(dlms, "_validate_staged_content_pack", return_value=report):
            pack_response = self.client.post(
                "/content-packs/import",
                data={"csrf_token": token, "pack_zip": (io.BytesIO(b"PK-test"), "pack.zip")},
                content_type="multipart/form-data",
            )
            self.assertEqual(pack_response.status_code, 302)
            self.assertIn("/content-packs/import/", pack_response.headers["Location"])

    def test_secret_key_is_persisted_reused_and_private(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(dlms, "APP_DATA_DIR", directory), mock.patch.dict(
            os.environ, {}, clear=False
        ):
            os.environ.pop("DLMS_SECRET_KEY", None)
            first = dlms.load_secret_key()
            second = dlms.load_secret_key()
            self.assertEqual(first, second)
            if os.name != "nt":
                mode = stat.S_IMODE(os.stat(os.path.join(directory, ".secret_key")).st_mode)
                self.assertEqual(mode, 0o600)
        with mock.patch.dict(os.environ, {"DLMS_SECRET_KEY": "managed-secret"}):
            self.assertEqual(dlms.load_secret_key(), "managed-secret")


class CsrfFrontendStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(dlms.STATIC_ROOT, "nav-normalize.js").read_text(encoding="utf-8")
        cls.app_source = Path(dlms.__file__).read_text(encoding="utf-8")

    def test_bootstrap_injects_only_same_origin_unsafe_forms(self):
        self.assertIn("document.querySelectorAll('form').forEach(protectForm)", self.source)
        self.assertIn("unsafeMethods.has(method)", self.source)
        self.assertIn("isSameOrigin(form.getAttribute('action'))", self.source)
        self.assertIn("field.name = 'csrf_token'", self.source)

    def test_fetch_wrapper_protects_unsafe_same_origin_requests_only(self):
        self.assertIn("window.fetch = (input, init = {})", self.source)
        self.assertIn("headers.set('X-CSRFToken', csrfToken)", self.source)
        self.assertIn("!unsafeMethods.has(method) || !isSameOrigin(requestUrl)", self.source)
        self.assertIn("init.headers", self.source)

    def test_direct_submit_anki_forms_are_explicitly_protected(self):
        self.assertEqual(self.app_source.count("window.dlmsProtectForm(exportForm);"), 2)
        self.assertEqual(self.app_source.count("exportForm.submit();"), 2)

    def test_mutation_pages_use_shared_bootstrap(self):
        for marker in (
            "/pdf-import/analyze", "/settings/backup/restore/stage", "/content-packs/import",
            "/api/clear_db_history", "/admin/rebuild_all_quiz_html",
        ):
            # A route can also appear in preflight tables and handlers. Find an
            # actual page/caller occurrence followed by the shared bootstrap.
            pattern = re.escape(marker) + r"[\s\S]{0,18000}?/static/nav-normalize\.js"
            self.assertRegex(self.app_source, pattern, marker)


if __name__ == "__main__":
    unittest.main()
