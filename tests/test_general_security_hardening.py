import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_IMPORT_DATA = tempfile.TemporaryDirectory(prefix="dlms-general-security-app-")
os.environ["QUIZAPP_DATA_DIR"] = _IMPORT_DATA.name

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers


class GeneralSecurityHardeningTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    def test_backup_exception_is_logged_without_browser_disclosure(self):
        sensitive = "/private/users/alice/results.db: sqlite page 9 corrupt"
        with mock.patch.object(dlms, "_create_dlms_backup", side_effect=RuntimeError(sensitive)), \
             mock.patch("builtins.print") as logged:
            response = self.client.post(
                "/settings/backup/create", headers=csrf_headers(self.client)
            )
        self.assertEqual(response.status_code, 500)
        body = response.get_data(as_text=True)
        self.assertNotIn(sensitive, body)
        self.assertNotIn("/private/users/alice", body)
        self.assertIn("could not create the backup", body)
        self.assertIn(sensitive, " ".join(str(call) for call in logged.call_args_list))

    def test_api_exception_returns_stable_json_and_logs_detail(self):
        sensitive = "OperationalError near /srv/private/results.db"
        connection = mock.MagicMock()
        connection.cursor.return_value.execute.return_value.fetchone.return_value = (7,)
        with mock.patch.object(dlms, "get_db", return_value=connection), \
             mock.patch.object(dlms, "_record_learning_event", side_effect=RuntimeError(sensitive)), \
             mock.patch("builtins.print") as logged:
            response = self.client.post(
                "/api/learning-events/study-response",
                json={"quizId": 1, "questionNumber": 1},
                headers=csrf_headers(self.client),
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"], "The learning event could not be recorded.")
        self.assertNotIn(sensitive, response.get_data(as_text=True))
        self.assertIn(sensitive, " ".join(str(call) for call in logged.call_args_list))

    def test_generated_quiz_source_links_use_http_https_allowlist(self):
        script = Path(dlms.STATIC_ROOT, "script.js").read_text(encoding="utf-8")
        start = script.index("function safeExternalUrl")
        block = script[start:script.index("/* =====================================================", start)]
        self.assertIn('["http:", "https:"].includes(url.protocol)', block)
        for unsafe in ("javascript:", "data:", "file:", "vbscript:", "ftp:"):
            self.assertNotIn(f'"{unsafe}"', block)
        self.assertIn("const sourceUrl = safeExternalUrl(source.url);", script)
        self.assertIn("sourceUrl ? `<div", script)

    def test_secret_is_persistent_private_and_excluded_from_backups(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(dlms, "APP_DATA_DIR", directory), \
             mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DLMS_SECRET_KEY", None)
            first = dlms.load_secret_key()
            second = dlms.load_secret_key()
            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first), 64)
            if os.name != "nt":
                self.assertEqual(
                    stat.S_IMODE(os.stat(os.path.join(directory, ".secret_key")).st_mode),
                    0o600,
                )
        self.assertTrue(dlms._backup_rel_is_excluded(".secret_key"))
        source = Path(dlms.__file__).read_text(encoding="utf-8")
        self.assertNotIn('app.secret_key = "dlms-dev"', source)
        with mock.patch.dict(os.environ, {"DLMS_SECRET_KEY": "managed-deployment-secret"}):
            self.assertEqual(dlms.load_secret_key(), "managed-deployment-secret")

    def test_security_headers_cover_html_and_api_without_global_cache_override(self):
        for path in ("/", "/api/portal_config"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertEqual(
                    response.headers["Permissions-Policy"],
                    "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
                )
        self.assertEqual(self.client.get("/api/portal_config").headers["Cache-Control"], "no-store")
        static_response = self.client.get("/static/style.css")
        try:
            self.assertNotEqual(static_response.headers.get("Cache-Control"), "no-store")
        finally:
            static_response.close()


if __name__ == "__main__":
    unittest.main()
