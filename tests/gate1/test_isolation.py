"""Fail-closed path and origin checks without starting the application."""
from __future__ import annotations

from pathlib import Path
import unittest

from PySide6.QtCore import QUrl

from desktop.isolation import AREA, assert_safe_leaf, isolated_environment, profile_paths
from desktop.shell import allowed_external, allowed_internal


class IsolationTests(unittest.TestCase):
    def test_explicit_disposable_profile_and_environment(self):
        paths = profile_paths("unit01")
        env = isolated_environment(paths)
        self.assertEqual(paths["root"].parent, AREA / "profiles")
        self.assertEqual(env["HOME"], str(paths["home"]))
        self.assertEqual(env["QUIZAPP_DATA_DIR"], str(paths["backend"]))
        self.assertEqual(env["XDG_DATA_HOME"], str(paths["xdg_data"]))
        self.assertEqual(env["TMPDIR"], str(paths["tmp"]))
        self.assertNotIn("QTWEBENGINE_DISABLE_SANDBOX", env)

    def test_reject_escaping_or_ambiguous_profile_names(self):
        for name in ("../owner", "/tmp/owner", "Owner", "", "a/../b", "a" * 33):
            with self.subTest(name=name), self.assertRaises(ValueError):
                profile_paths(name)

    def test_reject_profile_symlink(self):
        link = AREA / "profiles" / "unitlink"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(AREA / "profiles" / "unit01", target_is_directory=True)
        try:
            with self.assertRaises(ValueError):
                profile_paths("unitlink")
        finally:
            link.unlink()

    def test_reject_planted_output_symlink_and_directory(self):
        root = profile_paths("unit01")["root"]
        link = root / "backend.log"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(root / "elsewhere")
        try:
            with self.assertRaises(ValueError):
                assert_safe_leaf(link)
        finally:
            link.unlink()
        with self.assertRaises(ValueError):
            assert_safe_leaf(root / "logs")

    def test_exact_loopback_origin_and_external_scheme(self):
        self.assertTrue(allowed_internal(QUrl("http://127.0.0.1:9001/library"), 9001))
        for url in ("http://localhost:9001/", "http://127.0.0.1:9002/", "https://127.0.0.1:9001/", "http://user@127.0.0.1:9001/"):
            with self.subTest(url=url):
                self.assertFalse(allowed_internal(QUrl(url), 9001))
        self.assertTrue(allowed_external(QUrl("https://example.org/")))
        for url in ("file:///tmp/a", "javascript:alert(1)", "http://127.0.0.1:9001/", "http://localhost:80/"):
            with self.subTest(url=url):
                self.assertFalse(allowed_external(QUrl(url)))


if __name__ == "__main__":
    unittest.main()
