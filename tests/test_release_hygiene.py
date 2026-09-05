import json
import os
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
        self.assertEqual(version.group(1), "3.0.2")
        self.assertIn(f"Current release: DLMS {version.group(1)}", readme)
        self.assertNotIn("DLMS v2.1.0 is now available", readme)
        for setting in ("--browser", "--no-browser", "DLMS_NO_BROWSER"):
            self.assertIn(setting, readme)
        self.assertIn("interactive desktop session", readme)
        self.assertRegex(
            readme,
            r"Closing the\s+browser tab or window does not shut down DLMS",
        )
        self.assertRegex(readme, r"instead of starting another\s+server copy")
        self.assertIn("use **Shutdown DLMS**", readme)
        self.assertIn("requirements-lock.txt", readme)
        self.assertIn("GitHub's automatic source archives", readme)

    def test_release_metadata_and_help_use_the_final_display_version(self):
        version = "3.0.2"
        self.assertIn(f"Reproducible DLMS {version} runtime environment.", (ROOT / "requirements-lock.txt").read_text(encoding="utf-8"))
        self.assertIn(f"Canonical DLMS {version} build tools.", (ROOT / "requirements-build.txt").read_text(encoding="utf-8"))
        for path in (ROOT / "static").glob("*.html"):
            contents = path.read_text(encoding="utf-8")
            if "Documentation for DLMS" in contents:
                with self.subTest(page=path.name):
                    self.assertIn(f"Documentation for DLMS {version}.", contents)

    def test_current_release_text_has_no_prerelease_label(self):
        prerelease = re.compile(r"(?i)(?:\brc[._ -]?4\b|\bfc4\b)")
        paths = [
            ROOT / "app.py",
            ROOT / "README.md",
            ROOT / "DLMS.spec",
            ROOT / "docs" / "RELEASE_VERIFICATION.md",
            ROOT / "requirements-build.txt",
            ROOT / "requirements-lock.txt",
            ROOT / "release_assets" / "README.txt",
            ROOT / "release_assets" / "sample_quiz.txt",
            *(ROOT / "static").glob("*.html"),
        ]
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                contents = path.read_text(encoding="utf-8")
                self.assertNotRegex(contents, prerelease)

        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        dashboard = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(dashboard.count("DLMS v{{ app_version }}"), 2)
        self.assertEqual(app_source.count("DLMS v{{ app_version }}"), 5)
        self.assertEqual(
            app_source.count('lines.append(f"# Exported from DLMS v{APP_VERSION}")'),
            3,
        )

    def test_checksum_helper_rejects_noncanonical_or_incomplete_final_set(self):
        script = ROOT / "tools" / "generate_sha256sums.py"
        self.assertTrue(script.is_file())
        with tempfile.TemporaryDirectory(prefix="dlms-checksums-") as directory:
            root = Path(directory)
            artifacts = [root / "DLMS-3.0.2-RC4-windows-x86_64.zip"]
            manifest = root / "SHA256SUMS.txt"
            for artifact in artifacts:
                artifact.write_bytes(f"release artifact: {artifact.name}".encode())

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--output",
                    str(manifest),
                    *(str(artifact) for artifact in artifacts),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact canonical final package set", result.stderr)
            self.assertFalse(manifest.exists())

    def test_native_artifact_verification_is_a_documented_release_gate(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        procedure = (ROOT / "docs" / "RELEASE_VERIFICATION.md").read_text(encoding="utf-8")
        verifier = (ROOT / "tools" / "verify_release_artifact.py").read_text(encoding="utf-8")

        self.assertIn("docs/RELEASE_VERIFICATION.md", readme)
        for target in ("windows-x86_64", "linux-x86_64", "macos-arm64"):
            with self.subTest(target=target):
                self.assertIn(f"verify_release_artifact.py {target}", procedure)
        for artifact_name in (
            "DLMS-3.0.2-fedora44-x86_64",
            "DLMS-3.0.2-ubuntu24.04-x86_64",
            "DLMS-3.0.2-ubuntu26.04-x86_64",
            "DLMS-3.0.2-windows11-x86_64.exe",
            "DLMS-3.0.2-macos-arm64.zip",
            "DLMS-3.0.2-omarchy-quattro-x86_64",
        ):
            with self.subTest(artifact_name=artifact_name):
                self.assertIn(artifact_name, readme)
                self.assertIn(artifact_name, procedure)
        self.assertNotIn("DLMS-3.0.2-linux-x86_64", readme + procedure)
        self.assertNotIn("DLMS-3.0.2-windows-x86_64.exe", readme + procedure)
        self.assertIn("verify_release_package.py --complete-set", procedure)
        self.assertIn('--checksums "$PACKAGE_DIR/SHA256SUMS.txt"', procedure)
        self.assertIn("--smoke", procedure)
        self.assertIn("QUIZAPP_DATA_DIR", verifier)
        self.assertIn("Shutdown DLMS", procedure)
        self.assertIn("not sign, notarize, publish, upload, or create installers", procedure)

    def test_final_release_packages_and_authoritative_documents_are_documented(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        procedure = (ROOT / "docs" / "RELEASE_VERIFICATION.md").read_text(encoding="utf-8")
        package_readme = (ROOT / "release_assets" / "README.txt").read_text(
            encoding="utf-8"
        )
        package_verifier = ROOT / "tools" / "verify_release_package.py"
        packager = ROOT / "tools" / "package_release.py"
        final_packages = (
            "DLMS-3.0.2-fedora44-x86_64.tar.gz",
            "DLMS-3.0.2-ubuntu24.04-x86_64.tar.gz",
            "DLMS-3.0.2-ubuntu26.04-x86_64.tar.gz",
            "DLMS-3.0.2-windows11-x86_64.zip",
            "DLMS-3.0.2-macos-arm64.zip",
            "DLMS-3.0.2-omarchy-quattro-x86_64.tar.gz",
        )

        self.assertTrue(package_verifier.is_file())
        self.assertTrue(packager.is_file())
        for name in final_packages:
            with self.subTest(name=name):
                self.assertIn(name, readme)
                self.assertIn(name, procedure)
                self.assertIn(name, package_readme)
        self.assertIn("README.txt", procedure)
        self.assertIn("sample_quiz.txt", procedure)
        self.assertIn("--complete-set", procedure)
        self.assertIn("--checksums", procedure)
        self.assertIn("verify_release_package.py --smoke", procedure)
        self.assertIn("Expand-Archive", procedure)
        self.assertIn("promotes that ZIP byte-for-byte", procedure)
        self.assertIn("only root-level `DLMS.app`", procedure)
        self.assertNotIn(
            "DLMS-3.0.2-macos-arm64.zip\n└── DLMS-3.0.2-macos-arm64/",
            procedure,
        )
        self.assertIn(
            "The macOS ZIP is app-only and exposes\n`DLMS.app` directly",
            readme,
        )
        self.assertIn(
            "The macOS download is an\napp-only ZIP containing DLMS.app directly",
            package_readme,
        )
        self.assertIn("GitHub automatically supplies repository source", procedure)
        self.assertIn("Do not\ncreate or upload `DLMS-3.0.2-source.zip`", procedure)
        self.assertNotRegex(
            package_readme, re.compile(r"(?i)(?:\brc[._ -]?4\b|\bfc4\b)")
        )
        self.assertNotIn("git clone", package_readme)
        self.assertNotIn("PyInstaller", package_readme)

    def test_distributed_sample_quiz_uses_the_current_parser(self):
        sample = ROOT / "release_assets" / "sample_quiz.txt"
        with tempfile.TemporaryDirectory(prefix="dlms-sample-quiz-") as directory:
            environment = os.environ.copy()
            environment["QUIZAPP_DATA_DIR"] = directory
            environment["DLMS_NO_BROWSER"] = "1"
            code = (
                "import json, pathlib, app; "
                "questions = app.parse_questions("
                f"pathlib.Path({str(sample)!r}).read_text(encoding='utf-8')); "
                "print(json.dumps(questions))"
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        questions = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(len(questions), 10)
        self.assertTrue(all(len(question["correct"]) == 1 for question in questions))

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

        macos_zip = "DLMS-3.0.2-macos-arm64.zip"
        for document in (readme, getting_started):
            self.assertIn(macos_zip, document)
            self.assertIn("DLMS.app", document)
            self.assertIn("Control-click", document)
            self.assertIn("Open Anyway", document)

        self.assertIn("Privacy & Security", readme)
        self.assertIn("Privacy &amp; Security", getting_started)
        self.assertIn("ditto -c -k --sequesterRsrc --keepParent dist/DLMS.app", readme)
        self.assertIn("Contents/MacOS/DLMS", readme)
        self.assertNotIn("* macOS: `DLMS-3.0.2-macos-arm64`", readme)
        self.assertIn("not part of the normal installation", readme)
        self.assertGreater(
            readme.index("xattr -dr com.apple.quarantine /Applications/DLMS.app"),
            readme.index("Open Anyway"),
        )
        self.assertIn("xattr -dr com.apple.quarantine /Applications/DLMS.app", troubleshooting)
        self.assertIn("fallback troubleshooting rather than routine installation guidance", troubleshooting)

    def test_macos_bundle_version_fields_follow_current_release_metadata(self):
        spec = (ROOT / "DLMS.spec").read_text(encoding="utf-8")
        metadata_source = spec.split("bundle_data =", 1)[0]
        metadata = {"SPEC": str(ROOT / "DLMS.spec")}
        exec(compile(metadata_source, "DLMS.spec metadata", "exec"), metadata)

        self.assertEqual(metadata["app_release_version"], "3.0.2")
        self.assertEqual(metadata["app_bundle_version"], "3.0.2")
        self.assertEqual(metadata["app_bundle_build_version"], "3.0.2")
        self.assertIn("version=app_bundle_version", spec)
        self.assertIn('"CFBundleVersion": app_bundle_build_version', spec)
        self.assertIn('bundle_identifier="io.github.drakahari.DLMS"', spec)

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
