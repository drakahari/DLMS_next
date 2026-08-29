import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
