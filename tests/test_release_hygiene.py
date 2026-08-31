import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseDocumentationTests(unittest.TestCase):
    def test_readme_release_and_browser_controls_match_runtime_contract(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")

        version = re.search(r'^APP_VERSION = "([^"]+)"$', app_source, re.MULTILINE)
        self.assertIsNotNone(version)
        self.assertIn(f"Current release: DLMS {version.group(1)}", readme)
        self.assertNotIn("DLMS v2.1.0 is now available", readme)
        for setting in ("--browser", "--no-browser", "DLMS_NO_BROWSER"):
            self.assertIn(setting, readme)
        self.assertIn("interactive desktop session", readme)
        self.assertIn("requirements-lock.txt", readme)
        self.assertIn("git archive", readme)

    def test_runtime_requirements_are_bounded_and_lock_is_complete(self):
        requirements = [
            line.strip()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertTrue(requirements)
        for requirement in requirements:
            self.assertRegex(requirement, r">=[^,]+,<")

        locked = (ROOT / "requirements-lock.txt").read_text(encoding="utf-8")
        for package in ("Flask", "Flask-WTF", "genanki", "Werkzeug", "pypdf", "Pillow"):
            self.assertRegex(locked, rf"(?im)^{re.escape(package)}==[^\s]+$")

    def test_common_local_and_generated_artifacts_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for pattern in (
            ".venv/",
            "venv/",
            "__pycache__/",
            ".pytest_cache/",
            "dist/",
            "build/",
            "*.spec",
            "*.tmp",
            "*.log",
        ):
            self.assertIn(pattern, ignored)
        self.assertIn("!DLMS.spec", ignored)

    def test_canonical_pyinstaller_manifest_has_narrow_local_inputs(self):
        spec = (ROOT / "DLMS.spec").read_text(encoding="utf-8")
        build_requirements = (ROOT / "requirements-build.txt").read_text(encoding="utf-8")

        self.assertIn('project_root / "app.py"', spec)
        self.assertIn('project_root / "static"', spec)
        self.assertIn('project_root / "init.sql"', spec)
        self.assertNotIn("Tree(", spec)
        for forbidden in (
            "results.db",
            "portal.json",
            "quizzes.json",
            ".secret_key",
            "backups",
            "uploads",
            "tests",
            ".venv",
        ):
            self.assertNotIn(forbidden, spec)

        self.assertIn("-r requirements-lock.txt", build_requirements)
        self.assertRegex(build_requirements, r"(?m)^PyInstaller==[^\s]+$")
        self.assertRegex(build_requirements, r"(?m)^pyinstaller-hooks-contrib==[^\s]+$")

    def test_source_archive_excludes_confirmed_development_only_files(self):
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        for path in (
            "/AGENTS.md",
            "/archive",
            "/archive/**",
            "/legacy_library_ui_2026-08-21.txt",
            "/MATCHING_PROTOTYPE_NOTES.md",
            "/README_MEDICAL_V0.4.md",
            "/README_MEDICAL_V0.5.md",
            "/docs/screenshots/requirements.txt",
        ):
            self.assertRegex(attributes, rf"(?m)^{re.escape(path)}\s+export-ignore$")

        # Tests and runtime/help assets remain part of a verifiable source release.
        self.assertNotRegex(attributes, r"(?m)^/tests/\s+export-ignore$")
        self.assertNotRegex(attributes, r"(?m)^/static/\s+export-ignore$")


if __name__ == "__main__":
    unittest.main()
