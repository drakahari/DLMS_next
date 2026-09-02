import hashlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseDocumentationTests(unittest.TestCase):
    def test_readme_release_and_browser_controls_match_runtime_contract(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")

        version = re.search(r'^APP_VERSION = "([^"]+)"$', app_source, re.MULTILINE)
        self.assertIsNotNone(version)
        self.assertEqual(version.group(1), "3.0.2 RC4")
        self.assertIn(f"Current release: DLMS {version.group(1)}", readme)
        self.assertNotIn("DLMS v2.1.0 is now available", readme)
        for setting in ("--browser", "--no-browser", "DLMS_NO_BROWSER"):
            self.assertIn(setting, readme)
        self.assertIn("interactive desktop session", readme)
        self.assertIn("requirements-lock.txt", readme)
        self.assertIn("git archive", readme)

    def test_release_metadata_and_help_use_the_rc4_display_version(self):
        version = "3.0.2 RC4"
        self.assertIn(f"Reproducible DLMS {version} runtime environment.", (ROOT / "requirements-lock.txt").read_text(encoding="utf-8"))
        self.assertIn(f"Canonical DLMS {version} build tools.", (ROOT / "requirements-build.txt").read_text(encoding="utf-8"))
        for path in (ROOT / "static").glob("*.html"):
            contents = path.read_text(encoding="utf-8")
            if "Documentation for DLMS" in contents:
                with self.subTest(page=path.name):
                    self.assertIn(f"Documentation for DLMS {version}.", contents)

    def test_user_visible_release_text_does_not_drop_the_rc_label(self):
        bare_release = re.compile(r"DLMS(?: v)?3\.0\.2(?! RC4)")
        paths = [
            ROOT / "app.py",
            ROOT / "README.md",
            ROOT / "requirements-build.txt",
            ROOT / "requirements-lock.txt",
            *(ROOT / "static").glob("*.html"),
        ]
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                contents = path.read_text(encoding="utf-8")
                self.assertNotRegex(contents, bare_release)

        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        dashboard = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(dashboard.count("DLMS v{{ app_version }}"), 2)
        self.assertEqual(app_source.count("DLMS v{{ app_version }}"), 5)
        self.assertEqual(
            app_source.count('lines.append(f"# Exported from DLMS v{APP_VERSION}")'),
            3,
        )

    def test_checksum_helper_writes_standard_manifest_for_staged_artifacts(self):
        script = ROOT / "tools" / "generate_sha256sums.py"
        self.assertTrue(script.is_file())
        with tempfile.TemporaryDirectory(prefix="dlms-checksums-") as directory:
            root = Path(directory)
            windows = root / "DLMS-3.0.2-RC4-windows-x86_64.exe"
            linux = root / "DLMS-3.0.2-RC4-linux-x86_64"
            macos = root / "DLMS-3.0.2-RC4-macos-arm64.zip"
            manifest = root / "SHA256SUMS.txt"
            windows.write_bytes(b"windows release artifact")
            linux.write_bytes(b"linux release artifact")
            macos.write_bytes(b"macOS DLMS.app ZIP artifact")

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--output",
                    str(manifest),
                    str(windows),
                    str(linux),
                    str(macos),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                manifest.read_text(encoding="utf-8"),
                "\n".join((
                    f"{hashlib.sha256(linux.read_bytes()).hexdigest()}  {linux.name}",
                    f"{hashlib.sha256(macos.read_bytes()).hexdigest()}  {macos.name}",
                    f"{hashlib.sha256(windows.read_bytes()).hexdigest()}  {windows.name}",
                    "",
                )),
            )

    def test_macos_release_is_a_native_app_zip_with_first_run_guidance(self):
        spec = (ROOT / "DLMS.spec").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        getting_started = (ROOT / "static" / "help-getting-started.html").read_text(encoding="utf-8")
        troubleshooting = (ROOT / "static" / "help-troubleshooting.html").read_text(encoding="utf-8")

        compile(spec, "DLMS.spec", "exec")
        self.assertIn('if sys.platform == "darwin":', spec)
        self.assertIn("app_bundle = BUNDLE(", spec)
        self.assertIn('name="DLMS.app"', spec)
        self.assertIn("exclude_binaries=True", spec)
        self.assertIn("console=False", spec)
        self.assertIn('codesign_identity=None', spec)

        macos_zip = "DLMS-3.0.2-RC4-macos-arm64.zip"
        for document in (readme, getting_started):
            self.assertIn(macos_zip, document)
            self.assertIn("DLMS.app", document)
            self.assertIn("Control-click", document)
            self.assertIn("Open Anyway", document)

        self.assertIn("Privacy & Security", readme)
        self.assertIn("Privacy &amp; Security", getting_started)
        self.assertIn("ditto -c -k --sequesterRsrc --keepParent dist/DLMS.app", readme)
        self.assertIn("Contents/MacOS/DLMS", readme)
        self.assertNotIn("* macOS: `DLMS-3.0.2-RC4-macos-arm64`", readme)
        self.assertIn("not part of the normal installation", readme)
        self.assertGreater(
            readme.index("xattr -dr com.apple.quarantine /Applications/DLMS.app"),
            readme.index("Open Anyway"),
        )
        self.assertIn("xattr -dr com.apple.quarantine /Applications/DLMS.app", troubleshooting)
        self.assertIn("fallback troubleshooting rather than routine installation guidance", troubleshooting)

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
