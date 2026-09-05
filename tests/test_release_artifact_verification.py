"""Regression coverage for the native release artifact verification helper."""

import hashlib
import importlib.util
import os
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verify_release_artifact.py"
VERSION = "3.0.2"
SPEC = importlib.util.spec_from_file_location("release_artifact_verifier", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def _write_source_root(root: Path) -> None:
    (root / "app.py").write_text(f'APP_VERSION = "{VERSION}"\n', encoding="utf-8")


def _write_pe(path: Path) -> None:
    contents = bytearray(0x100)
    contents[:2] = b"MZ"
    contents[0x3C:0x40] = struct.pack("<I", 0x80)
    contents[0x80:0x84] = b"PE\0\0"
    contents[0x84:0x86] = struct.pack("<H", 0x8664)
    path.write_bytes(contents)


def _write_elf(path: Path) -> None:
    contents = bytearray(64)
    contents[:4] = b"\x7fELF"
    contents[4] = 2
    contents[5] = 1
    contents[18:20] = struct.pack("<H", 62)
    path.write_bytes(contents)


def _write_macos_zip(
    path: Path,
    *,
    runtime_member: str | None = None,
    bundle_version: str = VERSION,
) -> None:
    executable = b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + (b"\0" * 24)
    metadata = plistlib.dumps({
        "CFBundleGetInfoString": f"DLMS {bundle_version}",
        "CFBundleShortVersionString": bundle_version,
        "CFBundleVersion": bundle_version,
    })
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("DLMS.app/Contents/Info.plist", metadata)
        archive.writestr("DLMS.app/Contents/MacOS/DLMS", executable)
        archive.writestr("DLMS.app/Contents/Resources/static/style.css", "body {}")
        if runtime_member:
            archive.writestr(runtime_member, "must not ship")


class ReleaseArtifactVerificationTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_windows_artifact_name_architecture_and_checksum_are_verified(self):
        with tempfile.TemporaryDirectory(prefix="dlms-native-release-") as directory:
            root = Path(directory)
            _write_source_root(root)
            artifact = root / "DLMS-3.0.2-windows11-x86_64.exe"
            _write_pe(artifact)
            manifest = root / "SHA256SUMS.txt"
            manifest.write_text(
                f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}\n",
                encoding="utf-8",
            )

            result = self._run(
                "windows-x86_64", str(artifact), "--checksums", str(manifest),
                "--source-root", str(root),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Verified DLMS-3.0.2-windows11-x86_64.exe", result.stdout)

    def test_verifier_rejects_obsolete_generic_final_artifact_names(self):
        with tempfile.TemporaryDirectory(prefix="dlms-native-release-") as directory:
            root = Path(directory)
            _write_source_root(root)
            windows = root / "DLMS-3.0.2-windows-x86_64.exe"
            linux = root / "DLMS-3.0.2-linux-x86_64"
            _write_pe(windows)
            _write_elf(linux)
            linux.chmod(0o755)

            for target, artifact in (
                ("windows-x86_64", windows),
                ("linux-x86_64", linux),
            ):
                with self.subTest(target=target):
                    result = self._run(target, str(artifact), "--source-root", str(root))
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("Expected artifact name", result.stderr)

    def test_verifier_rejects_bad_name_or_checksum(self):
        with tempfile.TemporaryDirectory(prefix="dlms-native-release-") as directory:
            root = Path(directory)
            _write_source_root(root)
            artifact = root / "DLMS-windows.exe"
            _write_pe(artifact)
            manifest = root / "SHA256SUMS.txt"
            manifest.write_text(f"{'0' * 64}  {artifact.name}\n", encoding="utf-8")

            result = self._run(
                "windows-x86_64", str(artifact), "--checksums", str(manifest),
                "--source-root", str(root),
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Expected artifact name", result.stderr)
            self.assertIn("SHA256 mismatch", result.stderr)

    def test_macos_zip_requires_native_bundle_shape_architecture_and_no_runtime_data(self):
        with tempfile.TemporaryDirectory(prefix="dlms-native-release-") as directory:
            root = Path(directory)
            _write_source_root(root)
            artifact = root / "DLMS-3.0.2-macos-arm64.zip"
            _write_macos_zip(artifact)

            good = self._run("macos-arm64", str(artifact), "--source-root", str(root))
            self.assertEqual(good.returncode, 0, good.stderr)

            _write_macos_zip(artifact, bundle_version="9.9.9")
            wrong_version = self._run("macos-arm64", str(artifact), "--source-root", str(root))
            self.assertEqual(wrong_version.returncode, 1)
            self.assertIn("does not match APP_VERSION", wrong_version.stderr)

            _write_macos_zip(artifact, runtime_member="DLMS.app/Contents/Resources/results.db")
            bad = self._run("macos-arm64", str(artifact), "--source-root", str(root))
            self.assertEqual(bad.returncode, 1)
            self.assertIn("includes runtime/user data", bad.stderr)

    def test_macos_smoke_uses_ditto_to_preserve_the_bundled_app_structure(self):
        with tempfile.TemporaryDirectory(prefix="dlms-native-release-") as directory:
            root = Path(directory)
            artifact = root / "DLMS-3.0.2-macos-arm64.zip"
            _write_macos_zip(artifact)
            work_root = root / "smoke"
            executable = work_root / "macos-artifact" / "DLMS.app" / "Contents" / "MacOS" / "DLMS"
            ditto = root / "ditto"
            ditto.write_text("test ditto", encoding="utf-8")

            def emulate_ditto(command, **_kwargs):
                self.assertEqual(command[:3], [str(ditto), "-x", "-k"])
                executable.parent.mkdir(parents=True)
                executable.write_bytes(b"native app executable")
                executable.chmod(0o755)
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(VERIFIER, "MACOS_DITTO", ditto), mock.patch.object(
                VERIFIER.subprocess, "run", side_effect=emulate_ditto
            ) as run:
                command = VERIFIER._smoke_command(artifact, "macos-arm64", work_root)

            self.assertEqual(command, [str(executable), "--no-browser"])
            self.assertEqual(run.call_args.args[0], [str(ditto), "-x", "-k", str(artifact), str(work_root / "macos-artifact")])

    def test_failed_packaged_launch_exposes_bounded_log_diagnostics(self):
        with tempfile.TemporaryDirectory(prefix="dlms-native-release-") as directory:
            log = Path(directory) / "launch.log"
            log.write_text("PyInstaller framework resolution failed", encoding="utf-8")
            self.assertEqual(VERIFIER._launch_log_tail(log), "PyInstaller framework resolution failed")

    def test_macos_smoke_environment_keeps_data_isolation_but_removes_shell_python_overrides(self):
        data_root = Path("/tmp/dlms-smoke-data")
        environment = VERIFIER._smoke_environment(
            data_root,
            "macos-arm64",
            {
                "PYTHONHOME": "/wrong/python",
                "PYTHONPATH": "/wrong/path",
                "PYTHONEXECUTABLE": "/wrong/python",
                "__PYVENV_LAUNCHER__": "/wrong/python",
                "VIRTUAL_ENV": "/wrong/venv",
                "KEEP_ME": "yes",
            },
        )

        self.assertEqual(environment["QUIZAPP_DATA_DIR"], str(data_root))
        self.assertEqual(environment["DLMS_NO_BROWSER"], "1")
        self.assertEqual(environment["KEEP_ME"], "yes")
        for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "__PYVENV_LAUNCHER__", "VIRTUAL_ENV"):
            self.assertNotIn(name, environment)

    def test_linux_environment_names_require_executable_x86_64_elf(self):
        with tempfile.TemporaryDirectory(prefix="dlms-native-release-") as directory:
            root = Path(directory)
            _write_source_root(root)
            artifact = root / "DLMS-3.0.2-fedora44-x86_64"
            _write_elf(artifact)
            artifact.chmod(0o644)

            blocked = self._run("linux-x86_64", str(artifact), "--source-root", str(root))
            self.assertEqual(blocked.returncode, 1)
            self.assertIn("not marked executable", blocked.stderr)

            for suffix in (
                "fedora44-x86_64",
                "ubuntu24.04-x86_64",
                "ubuntu26.04-x86_64",
                "omarchy-quattro-x86_64",
            ):
                with self.subTest(suffix=suffix):
                    artifact = root / f"DLMS-3.0.2-{suffix}"
                    _write_elf(artifact)
                    artifact.chmod(0o755)
                    passed = self._run("linux-x86_64", str(artifact), "--source-root", str(root))
                    self.assertEqual(passed.returncode, 0, passed.stderr)

    def test_expected_data_directory_can_be_reported_without_an_artifact_or_app_import(self):
        result = self._run("macos-arm64", "--print-expected-data-dir")

        self.assertEqual(result.returncode, 0, result.stderr)
        expected = (
            str(Path.home() / "Library" / "Application Support" / "DLMS")
            if sys.platform == "darwin"
            else "~/Library/Application Support/DLMS"
        )
        self.assertEqual(result.stdout.strip(), expected)
        self.assertNotIn("Database schema", result.stdout + result.stderr)

    def test_shutdown_uses_session_bound_csrf_and_same_origin_browser_headers(self):
        client = mock.Mock()
        client.csrf_token.return_value = "session-bound-token"
        process = mock.Mock()
        process.returncode = 0
        with mock.patch.object(VERIFIER, "_request", return_value=(200, b'{"status":"ok"}')) as request:
            VERIFIER._shutdown_cleanly(process, client, "linux-x86_64")

        request.assert_called_once_with(
            "/api/shutdown",
            method="POST",
            client=client,
            headers={
                "X-CSRFToken": "session-bound-token",
                "Origin": VERIFIER.SERVER_URL,
                "Referer": f"{VERIFIER.SERVER_URL}/",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        process.wait.assert_called_once_with(timeout=VERIFIER.SHUTDOWN_TIMEOUT_SECONDS)

    def test_shutdown_rejection_is_not_hidden_or_bypassed(self):
        client = mock.Mock()
        client.csrf_token.return_value = "session-bound-token"
        process = mock.Mock()
        with mock.patch.object(VERIFIER, "_request", return_value=(400, b'{"error":"missing token"}')):
            with self.assertRaisesRegex(RuntimeError, "Shutdown DLMS returned HTTP 400"):
                VERIFIER._shutdown_cleanly(process, client, "windows-x86_64")
        process.wait.assert_not_called()

    def test_windows_sigint_exit_two_is_accepted_only_after_successful_shutdown(self):
        client = mock.Mock()
        client.csrf_token.return_value = "session-bound-token"
        process = mock.Mock()
        process.returncode = 2
        with mock.patch.object(VERIFIER, "_request", return_value=(200, b'{"status":"ok"}')):
            VERIFIER._shutdown_cleanly(process, client, "windows-x86_64")

        self.assertEqual(VERIFIER._clean_shutdown_returncodes("windows-x86_64"), {0, 2})
        self.assertNotIn(2, VERIFIER._clean_shutdown_returncodes("linux-x86_64"))
        self.assertNotIn(1, VERIFIER._clean_shutdown_returncodes("windows-x86_64"))

    def test_unexpected_windows_exit_after_shutdown_remains_a_failure(self):
        client = mock.Mock()
        client.csrf_token.return_value = "session-bound-token"
        process = mock.Mock()
        process.returncode = 1
        with mock.patch.object(VERIFIER, "_request", return_value=(200, b'{"status":"ok"}')):
            with self.assertRaisesRegex(RuntimeError, "exit code 1"):
                VERIFIER._shutdown_cleanly(process, client, "windows-x86_64")


if __name__ == "__main__":
    unittest.main()
