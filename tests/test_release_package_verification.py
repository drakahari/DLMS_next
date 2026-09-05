import io
import hashlib
import plistlib
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_release_package as PACKAGE_VERIFIER


SCRIPT = ROOT / "tools" / "verify_release_package.py"
PACKAGER = ROOT / "tools" / "package_release.py"
CHECKSUMMER = ROOT / "tools" / "generate_sha256sums.py"
VERSION = "3.0.2"


def elf_x86_64() -> bytes:
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = struct.pack("<H", 62)
    return bytes(header)


def pe_x86_64() -> bytes:
    binary = bytearray(256)
    binary[:2] = b"MZ"
    binary[0x3C:0x40] = struct.pack("<I", 0x80)
    binary[0x80:0x84] = b"PE\0\0"
    binary[0x84:0x86] = struct.pack("<H", 0x8664)
    return bytes(binary)


def macho_arm64() -> bytes:
    return b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + b"\0" * 24


def add_tar_file(archive, name, contents, mode=0o644):
    info = tarfile.TarInfo(name)
    info.size = len(contents)
    info.mode = mode
    archive.addfile(info, io.BytesIO(contents))


def add_zip_file(archive, name, contents, mode=0o644):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    archive.writestr(info, contents)


def add_zip_symlink(archive, name, target):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive.writestr(info, target)


class ReleasePackageVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-package-verification-")
        self.root = Path(self.temporary.name)
        self.readme = (ROOT / "release_assets" / "README.txt").read_bytes()
        self.sample = (ROOT / "release_assets" / "sample_quiz.txt").read_bytes()

    def tearDown(self):
        self.temporary.cleanup()

    def verify(self, package):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(package),
                "--source-root",
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def make_linux(self, platform_name, *, executable_mode=0o755, extra=None):
        wrapper = f"DLMS-{VERSION}-{platform_name}"
        path = self.root / f"{wrapper}.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            directory = tarfile.TarInfo(wrapper)
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o755
            archive.addfile(directory)
            add_tar_file(archive, f"{wrapper}/{wrapper}", elf_x86_64(), executable_mode)
            add_tar_file(archive, f"{wrapper}/README.txt", self.readme)
            add_tar_file(archive, f"{wrapper}/sample_quiz.txt", self.sample)
            if extra:
                add_tar_file(archive, f"{wrapper}/{extra}", b"unwanted")
        return path

    def make_windows(
        self,
        *,
        archive_name=None,
        executable_name=None,
        include_readme=True,
        include_sample=True,
        readme=None,
        wrapper=None,
        extra_executable=None,
    ):
        expected_wrapper = f"DLMS-{VERSION}-windows11-x86_64"
        wrapper = expected_wrapper if wrapper is None else wrapper
        path = self.root / (archive_name or f"{expected_wrapper}.zip")
        executable_name = executable_name or f"{expected_wrapper}.exe"
        with zipfile.ZipFile(path, "w") as archive:
            add_zip_file(archive, f"{wrapper}/{executable_name}", pe_x86_64())
            if include_readme:
                add_zip_file(
                    archive,
                    f"{wrapper}/README.txt",
                    self.readme if readme is None else readme,
                )
            if include_sample:
                add_zip_file(archive, f"{wrapper}/sample_quiz.txt", self.sample)
            if extra_executable:
                add_zip_file(
                    archive, f"{wrapper}/{extra_executable}", pe_x86_64()
                )
        return path

    def make_macos(
        self,
        *,
        wrapped=False,
        include_documents=False,
        identifier="io.github.drakahari.DLMS",
        symlink_target=None,
    ):
        archive_name = f"DLMS-{VERSION}-macos-arm64.zip"
        path = self.root / archive_name
        prefix = f"DLMS-{VERSION}-macos-arm64/" if wrapped else ""
        plist = plistlib.dumps(
            {
                "CFBundleExecutable": "DLMS",
                "CFBundleIdentifier": identifier,
                "CFBundleGetInfoString": f"DLMS {VERSION}",
                "CFBundleShortVersionString": VERSION,
                "CFBundleVersion": VERSION,
            }
        )
        with zipfile.ZipFile(path, "w") as archive:
            if include_documents:
                add_zip_file(archive, f"{prefix}README.txt", self.readme)
                add_zip_file(archive, f"{prefix}sample_quiz.txt", self.sample)
            add_zip_file(
                archive,
                f"{prefix}DLMS.app/Contents/Info.plist",
                plist,
            )
            add_zip_file(
                archive,
                f"{prefix}DLMS.app/Contents/MacOS/DLMS",
                macho_arm64(),
                0o755,
            )
            add_zip_file(
                archive,
                f"{prefix}DLMS.app/Contents/Resources/static/style.css",
                b"body {}",
            )
            if symlink_target is not None:
                add_zip_symlink(
                    archive,
                    f"{prefix}DLMS.app/Contents/Frameworks/Current",
                    symlink_target,
                )
        return path

    def make_staged_artifacts(self):
        staging = self.root / "staging"
        staging.mkdir()
        for platform_name in (
            "fedora44-x86_64",
            "ubuntu24.04-x86_64",
            "ubuntu26.04-x86_64",
            "omarchy-quattro-x86_64",
        ):
            artifact = staging / f"DLMS-{VERSION}-{platform_name}"
            artifact.write_bytes(elf_x86_64())
            artifact.chmod(0o755)
        (staging / f"DLMS-{VERSION}-windows11-x86_64.exe").write_bytes(pe_x86_64())
        macos = staging / f"DLMS-{VERSION}-macos-arm64.zip"
        plist = plistlib.dumps(
            {
                "CFBundleExecutable": "DLMS",
                "CFBundleIdentifier": "io.github.drakahari.DLMS",
                "CFBundleGetInfoString": f"DLMS {VERSION}",
                "CFBundleShortVersionString": VERSION,
                "CFBundleVersion": VERSION,
            }
        )
        with zipfile.ZipFile(macos, "w") as archive:
            add_zip_file(archive, "DLMS.app/Contents/Info.plist", plist)
            add_zip_file(
                archive,
                "DLMS.app/Contents/MacOS/DLMS",
                macho_arm64(),
                0o755,
            )
            add_zip_file(
                archive,
                "DLMS.app/Contents/Resources/static/style.css",
                b"body {}",
            )
            add_zip_symlink(
                archive,
                "DLMS.app/Contents/Frameworks/Current",
                "Versions/Current",
            )
        return staging

    def test_complete_final_package_set_has_only_expected_payload(self):
        packages = [
            self.make_linux("fedora44-x86_64"),
            self.make_linux("ubuntu24.04-x86_64"),
            self.make_linux("ubuntu26.04-x86_64"),
            self.make_windows(),
            self.make_macos(),
            self.make_linux("omarchy-quattro-x86_64"),
        ]

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                *(str(package) for package in packages),
                "--complete-set",
                "--source-root",
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("Verified release package:"), 6)

        manifest = self.root / "SHA256SUMS.txt"
        generated = subprocess.run(
            [
                sys.executable,
                str(CHECKSUMMER),
                "--output",
                str(manifest),
                *(str(package) for package in packages),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(generated.returncode, 0, generated.stderr)
        checked = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                *(str(package) for package in packages),
                "--complete-set",
                "--checksums",
                str(manifest),
                "--source-root",
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("Verified checksum manifest:", checked.stdout)

    def test_macos_final_zip_is_app_only_at_archive_root(self):
        passed = self.verify(self.make_macos())

        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)

    def test_macos_versioned_wrapper_regression_is_rejected(self):
        failed = self.verify(self.make_macos(wrapped=True))

        self.assertEqual(failed.returncode, 1)
        self.assertIn("outside the required DLMS.app/ root", failed.stdout)
        self.assertIn("macOS package is missing", failed.stdout)

    def test_macos_release_documents_are_not_required_or_allowed(self):
        self.assertEqual(self.verify(self.make_macos()).returncode, 0)
        failed = self.verify(self.make_macos(include_documents=True))

        self.assertEqual(failed.returncode, 1)
        self.assertIn("outside the required DLMS.app/ root", failed.stdout)

    def test_macos_bundle_identifier_is_enforced(self):
        failed = self.verify(self.make_macos(identifier="invalid.example.DLMS"))

        self.assertEqual(failed.returncode, 1)
        self.assertIn("CFBundleIdentifier", failed.stdout)

    def test_macos_bundle_symlink_must_remain_inside_app(self):
        self.assertEqual(
            self.verify(self.make_macos(symlink_target="Versions/Current")).returncode,
            0,
        )
        failed = self.verify(self.make_macos(symlink_target="../../../../etc"))

        self.assertEqual(failed.returncode, 1)
        self.assertIn("symlink escapes DLMS.app", failed.stdout)

    def test_windows_stable_archive_and_executable_names_pass(self):
        passed = self.verify(self.make_windows())

        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)

    def test_final_package_names_derive_from_release_version(self):
        version = "4.1.0"
        packages = PACKAGE_VERIFIER.expected_packages(version)

        windows_name = f"DLMS-{version}-windows11-x86_64.zip"
        self.assertIn(windows_name, packages)
        self.assertEqual(
            packages[windows_name].executable,
            f"DLMS-{version}-windows11-x86_64.exe",
        )
        self.assertIn(f"DLMS-{version}-macos-arm64.zip", packages)

    def test_windows_incorrect_archive_name_fails(self):
        failed = self.verify(
            self.make_windows(archive_name=f"DLMS-{VERSION}-windows-x86_64.zip")
        )

        self.assertEqual(failed.returncode, 1)
        self.assertIn("unexpected final package filename", failed.stdout)

    def test_windows_generic_or_stale_executable_name_fails(self):
        for executable_name in ("DLMS.exe", f"DLMS-{VERSION}-windows-x86_64.exe"):
            with self.subTest(executable_name=executable_name):
                failed = self.verify(
                    self.make_windows(executable_name=executable_name)
                )
                self.assertEqual(failed.returncode, 1)
                self.assertIn("Windows package is missing", failed.stdout)
                self.assertIn("Windows package contains extra files", failed.stdout)

    def test_windows_requires_both_release_documents(self):
        for option in ("include_readme", "include_sample"):
            with self.subTest(missing=option):
                arguments = {option: False}
                failed = self.verify(self.make_windows(**arguments))
                self.assertEqual(failed.returncode, 1)
                self.assertIn("Windows package is missing", failed.stdout)

    def test_windows_duplicate_executable_name_fails(self):
        failed = self.verify(self.make_windows(extra_executable="DLMS.exe"))

        self.assertEqual(failed.returncode, 1)
        self.assertIn("Windows package contains extra files", failed.stdout)

    def test_windows_incorrect_wrapper_fails(self):
        failed = self.verify(self.make_windows(wrapper="DLMS"))

        self.assertEqual(failed.returncode, 1)
        self.assertIn("outside the required", failed.stdout)

    def test_windows_rejects_unsafe_and_case_colliding_members(self):
        package = self.make_windows()
        wrapper = f"DLMS-{VERSION}-windows11-x86_64"
        with zipfile.ZipFile(package, "a") as archive:
            add_zip_file(archive, "../DLMS.exe", pe_x86_64())
            add_zip_file(archive, f"{wrapper}/README.TXT", self.readme)

        failed = self.verify(package)

        self.assertEqual(failed.returncode, 1)
        self.assertIn("unsafe archive member path", failed.stdout)
        self.assertIn("case-colliding or duplicate members", failed.stdout)

    def test_linux_package_requires_preserved_executable_permission(self):
        package = self.make_linux("fedora44-x86_64", executable_mode=0o644)

        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(package), "--source-root", str(ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("execute permission bit", result.stdout)

    def test_package_rejects_development_or_runtime_junk(self):
        package = self.make_linux("ubuntu24.04-x86_64", extra="results.db")

        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(package), "--source-root", str(ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("forbidden", result.stdout)
        self.assertIn("extra files", result.stdout)

    def test_packaged_documents_must_match_authoritative_sources(self):
        package = self.make_windows(readme=b"stale README")

        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(package), "--source-root", str(ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match release_assets/README.txt", result.stdout)

    def test_checksum_manifest_must_cover_exact_supplied_package_set(self):
        package = self.make_linux("omarchy-quattro-x86_64")
        manifest = self.root / "SHA256SUMS.txt"
        manifest.write_text("0" * 64 + "  unrelated.zip\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(package),
                "--checksums",
                str(manifest),
                "--source-root",
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("checksum manifest is missing", result.stdout)
        self.assertIn("checksum manifest contains unexpected files", result.stdout)

    def test_packager_consumes_staged_artifacts_without_modifying_them(self):
        staging = self.make_staged_artifacts()
        def fingerprints():
            return {
                path.name: (
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    stat.S_IMODE(path.stat().st_mode),
                    path.stat().st_mtime_ns,
                )
                for path in staging.iterdir()
            }

        before = fingerprints()
        output = self.root / "final"

        result = subprocess.run(
            [
                sys.executable,
                str(PACKAGER),
                str(staging),
                str(output),
                "--source-root",
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(list(output.iterdir())), 6)
        self.assertEqual(
            result.stdout.count("Created and structurally verified final package:"),
            6,
        )
        self.assertIn("Native clean-extraction smoke is still required", result.stdout)
        self.assertEqual(before, fingerprints())
        macos_package = output / f"DLMS-{VERSION}-macos-arm64.zip"
        staged_macos = staging / macos_package.name
        self.assertEqual(
            hashlib.sha256(macos_package.read_bytes()).hexdigest(),
            hashlib.sha256(staged_macos.read_bytes()).hexdigest(),
        )
        with zipfile.ZipFile(macos_package) as archive:
            names = {info.filename.rstrip("/") for info in archive.infolist()}
            self.assertTrue(
                all(name == "DLMS.app" or name.startswith("DLMS.app/") for name in names)
            )
            self.assertNotIn("README.txt", names)
            self.assertNotIn("sample_quiz.txt", names)
            symlink_name = "DLMS.app/Contents/Frameworks/Current"
            symlink = archive.getinfo(symlink_name)
            self.assertTrue(stat.S_ISLNK(symlink.external_attr >> 16))
            self.assertEqual(archive.read(symlink), b"Versions/Current")

        second = subprocess.run(
            [
                sys.executable,
                str(PACKAGER),
                str(staging),
                str(output),
                "--source-root",
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(second.returncode, 1)
        self.assertIn("refusing to overwrite", second.stderr)

    def test_linux_final_package_is_clean_extracted_before_smoke(self):
        package = self.make_linux("fedora44-x86_64")
        spec = PACKAGE_VERIFIER.expected_packages(VERSION)[package.name]
        extraction_root = self.root / "linux-extracted"

        PACKAGE_VERIFIER._extract_final_package(package, spec, extraction_root)
        executable, errors = PACKAGE_VERIFIER.verify_extracted_release_package(
            package, extraction_root, spec, ROOT
        )

        self.assertEqual(errors, [])
        self.assertEqual(
            executable.relative_to(extraction_root).as_posix(),
            f"DLMS-{VERSION}-fedora44-x86_64/DLMS-{VERSION}-fedora44-x86_64",
        )
        self.assertTrue(executable.stat().st_mode & stat.S_IXUSR)

    def test_macos_clean_extraction_requires_root_app_and_validates_bundle(self):
        package = self.make_macos()
        spec = PACKAGE_VERIFIER.expected_packages(VERSION)[package.name]
        extraction_root = self.root / "macos-extracted"
        extraction_root.mkdir()
        with zipfile.ZipFile(package) as archive:
            archive.extractall(extraction_root)
        executable = extraction_root / "DLMS.app/Contents/MacOS/DLMS"
        executable.chmod(0o755)

        resolved, errors = PACKAGE_VERIFIER.verify_extracted_release_package(
            package, extraction_root, spec, ROOT
        )

        self.assertEqual(errors, [])
        self.assertEqual(resolved, executable)

    def test_windows_clean_extraction_validates_stable_wrapper_and_files(self):
        package = self.make_windows()
        spec = PACKAGE_VERIFIER.expected_packages(VERSION)[package.name]
        extraction_root = self.root / "windows-extracted"
        extraction_root.mkdir()
        with zipfile.ZipFile(package) as archive:
            archive.extractall(extraction_root)

        executable, errors = PACKAGE_VERIFIER.verify_extracted_release_package(
            package, extraction_root, spec, ROOT
        )

        self.assertEqual(errors, [])
        self.assertEqual(
            executable.name, f"DLMS-{VERSION}-windows11-x86_64.exe"
        )

    def test_windows_final_extraction_uses_expand_archive(self):
        package = self.make_windows()
        spec = PACKAGE_VERIFIER.expected_packages(VERSION)[package.name]
        extraction_root = self.root / "powershell-extracted"
        powershell = self.root / "powershell.exe"
        powershell.write_bytes(b"test")

        with mock.patch.object(
            PACKAGE_VERIFIER, "WINDOWS_POWERSHELL", powershell
        ), mock.patch.object(
            PACKAGE_VERIFIER.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ) as run:
            PACKAGE_VERIFIER._extract_final_package(
                package, spec, extraction_root
            )

        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertIn("Expand-Archive", command[-1])
        self.assertEqual(environment["DLMS_RELEASE_ARCHIVE"], str(package))
        self.assertEqual(
            environment["DLMS_RELEASE_DESTINATION"], str(extraction_root)
        )

    def test_macos_final_extraction_uses_ditto(self):
        package = self.make_macos()
        spec = PACKAGE_VERIFIER.expected_packages(VERSION)[package.name]
        extraction_root = self.root / "ditto-extracted"
        ditto = self.root / "ditto"
        ditto.write_bytes(b"test")

        with mock.patch.object(
            PACKAGE_VERIFIER, "MACOS_DITTO", ditto
        ), mock.patch.object(
            PACKAGE_VERIFIER.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ) as run:
            PACKAGE_VERIFIER._extract_final_package(
                package, spec, extraction_root
            )

        self.assertEqual(
            run.call_args.args[0],
            [str(ditto), "-x", "-k", str(package), str(extraction_root)],
        )

    def test_native_smoke_receives_executable_from_clean_final_extraction(self):
        package = self.make_linux("ubuntu24.04-x86_64")

        with mock.patch.object(
            PACKAGE_VERIFIER, "_assert_smoke_host"
        ), mock.patch.object(
            PACKAGE_VERIFIER, "smoke_test_executable"
        ) as smoke:
            errors = PACKAGE_VERIFIER.clean_extract_and_smoke(package, ROOT)

        self.assertEqual(errors, [])
        extracted_executable = smoke.call_args.args[0]
        self.assertEqual(
            extracted_executable.name,
            f"DLMS-{VERSION}-ubuntu24.04-x86_64",
        )
        self.assertIn("dlms-final-package-extraction-", str(extracted_executable))

    def test_checksum_generation_rejects_invalid_canonical_package(self):
        packages = [
            self.make_linux("fedora44-x86_64"),
            self.make_linux("ubuntu24.04-x86_64"),
            self.make_linux("ubuntu26.04-x86_64"),
            self.make_windows(include_readme=False),
            self.make_macos(),
            self.make_linux("omarchy-quattro-x86_64"),
        ]
        manifest = self.root / "SHA256SUMS.txt"

        result = subprocess.run(
            [
                sys.executable,
                str(CHECKSUMMER),
                "--output",
                str(manifest),
                *(str(package) for package in packages),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed validation", result.stderr)
        self.assertFalse(manifest.exists())


if __name__ == "__main__":
    unittest.main()
