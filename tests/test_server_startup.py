import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms


class ServerStartupTests(unittest.TestCase):
    def test_default_host_is_loopback(self):
        options = dlms._dlms_parse_startup_options(
            [], environ={}, desktop_available=True
        )
        self.assertEqual(dlms.DLMS_SERVER_HOST, "127.0.0.1")
        self.assertEqual(options["host"], "127.0.0.1")
        self.assertTrue(options["open_browser"])

    def test_explicit_non_loopback_host_is_supported_and_warned(self):
        options = dlms._dlms_parse_startup_options(
            ["--host", "0.0.0.0", "--no-browser"],
            environ={},
            desktop_available=True,
        )
        self.assertEqual(options["host"], "0.0.0.0")
        self.assertFalse(options["open_browser"])

        output = io.StringIO()
        with mock.patch.object(dlms, "_dlms_detect_lan_ip", return_value="192.168.1.25"):
            with redirect_stdout(output):
                dlms._dlms_print_access_urls(options["host"], 9001)
        rendered = output.getvalue()
        self.assertIn("http://192.168.1.25:9001", rendered)
        self.assertIn("Authentication is not yet provided", rendered)

    def test_browser_flags_do_not_change_bind_address(self):
        browser = dlms._dlms_parse_startup_options(
            ["--browser"], environ={}, desktop_available=False
        )
        no_browser = dlms._dlms_parse_startup_options(
            ["--no-browser"], environ={}, desktop_available=True
        )
        self.assertEqual(browser["host"], "127.0.0.1")
        self.assertEqual(no_browser["host"], "127.0.0.1")
        self.assertTrue(browser["open_browser"])
        self.assertFalse(no_browser["open_browser"])

    def test_browser_disable_sources_take_precedence_over_force_browser(self):
        cases = (
            (["--browser", "--no-browser"], {}, True),
            (["--no-browser", "--browser"], {}, True),
            (["--browser"], {"DLMS_NO_BROWSER": " YES "}, False),
            ([], {"DLMS_NO_BROWSER": "0"}, True),
        )
        for argv, environ, desktop_available in cases:
            with self.subTest(argv=argv, environ=environ):
                options = dlms._dlms_parse_startup_options(
                    argv, environ=environ, desktop_available=desktop_available
                )
                expected_disabled = (
                    "--no-browser" in argv
                    or str(environ.get("DLMS_NO_BROWSER") or "").strip().lower()
                    in {"1", "true", "yes", "on"}
                )
                self.assertEqual(expected_disabled, options["disable_browser"])
                self.assertEqual(not expected_disabled, options["open_browser"])

    def test_headless_and_environment_no_browser_are_independent_of_host(self):
        headless = dlms._dlms_parse_startup_options(
            ["--host=192.168.1.40"], environ={}, desktop_available=False
        )
        env_disabled = dlms._dlms_parse_startup_options(
            ["--host", "0.0.0.0"],
            environ={"DLMS_NO_BROWSER": "true"},
            desktop_available=True,
        )
        self.assertEqual(headless["host"], "192.168.1.40")
        self.assertFalse(headless["open_browser"])
        self.assertEqual(env_disabled["host"], "0.0.0.0")
        self.assertTrue(env_disabled["disable_browser"])
        self.assertFalse(env_disabled["open_browser"])

    def test_invalid_or_missing_host_is_rejected(self):
        invalid_values = ["", "http://0.0.0.0", "host name", "--no-browser"]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    dlms._dlms_parse_startup_options(
                        ["--host", value], environ={}, desktop_available=False
                    )
        with self.assertRaises(ValueError):
            dlms._dlms_parse_startup_options(
                ["--host"], environ={}, desktop_available=False
            )

    def test_host_validation_and_formatting_cover_ipv4_ipv6_and_names(self):
        for value, expected in (
            (" 127.0.0.1 ", "127.0.0.1"),
            ("::1", "::1"),
            ("study-host.local", "study-host.local"),
        ):
            with self.subTest(value=value):
                self.assertEqual(expected, dlms._dlms_validate_server_host(value))

        for host, expected in (
            ("localhost", True),
            ("LOCALHOST", True),
            ("127.0.0.2", True),
            ("::1", True),
            ("0.0.0.0", False),
            ("study-host.local", False),
        ):
            with self.subTest(host=host):
                self.assertEqual(expected, dlms._dlms_is_loopback_host(host))

        self.assertEqual("127.0.0.1", dlms._dlms_url_host("127.0.0.1"))
        self.assertEqual("[::1]", dlms._dlms_url_host("::1"))
        self.assertEqual("[::1]", dlms._dlms_url_host("[::1]"))
        self.assertEqual("127.0.0.1", dlms._dlms_browser_host("0.0.0.0"))
        self.assertEqual("127.0.0.1", dlms._dlms_browser_host("::"))
        self.assertEqual("::1", dlms._dlms_browser_host("::1"))

    def test_unknown_arguments_remain_ignored_and_last_host_wins(self):
        options = dlms._dlms_parse_startup_options(
            ["--unknown", "--host=127.0.0.2", "--host", "::1"],
            environ={},
            desktop_available=False,
        )
        self.assertEqual("::1", options["host"])
        self.assertFalse(options["open_browser"])

    def test_desktop_detection_preserves_platform_display_and_ssh_rules(self):
        with mock.patch.dict(dlms.os.environ, {}, clear=True), mock.patch.object(
            dlms.sys, "platform", "linux"
        ):
            self.assertFalse(dlms._dlms_desktop_browser_available())
            dlms.os.environ["DISPLAY"] = ":0"
            self.assertTrue(dlms._dlms_desktop_browser_available())
            dlms.os.environ["SSH_CONNECTION"] = "remote"
            self.assertFalse(dlms._dlms_desktop_browser_available())

        for platform in ("win32", "darwin"):
            with self.subTest(platform=platform), mock.patch.dict(
                dlms.os.environ, {}, clear=True
            ), mock.patch.object(dlms.sys, "platform", platform):
                self.assertTrue(dlms._dlms_desktop_browser_available())

    def test_access_output_preserves_loopback_ipv6_and_lan_messages(self):
        cases = (
            (
                "localhost",
                None,
                "[DLMS] Local access:   http://127.0.0.1:9001\n",
            ),
            (
                "::1",
                None,
                "[DLMS] Local access:   http://[::1]:9001\n",
            ),
            (
                "0.0.0.0",
                None,
                "[DLMS] Local access:   http://127.0.0.1:9001\n"
                "[DLMS] Network bind:   0.0.0.0:9001 (all interfaces)\n"
                "[DLMS] WARNING: DLMS is bound to a non-loopback interface.\n"
                "[DLMS] WARNING: Authentication is not yet provided; expose DLMS only on a trusted network.\n",
            ),
            (
                "2001:db8::4",
                None,
                "[DLMS] Network access: http://[2001:db8::4]:9001\n"
                "[DLMS] WARNING: DLMS is bound to a non-loopback interface.\n"
                "[DLMS] WARNING: Authentication is not yet provided; expose DLMS only on a trusted network.\n",
            ),
        )
        for host, lan_ip, expected in cases:
            with self.subTest(host=host):
                output = io.StringIO()
                with mock.patch.object(dlms, "_dlms_detect_lan_ip", return_value=lan_ip):
                    with redirect_stdout(output):
                        dlms._dlms_print_access_urls(host, 9001)
                self.assertEqual(expected, output.getvalue())


if __name__ == "__main__":
    unittest.main()
