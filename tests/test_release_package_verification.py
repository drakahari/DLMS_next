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


ROOT = Path(__file__).resolve().parents[1]
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

    def make_windows(self, *, readme=None):
        wrapper = f"DLMS-{VERSION}-windows11-x86_64"
        path = self.root / f"{wrapper}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            add_zip_file(archive, f"{wrapper}/{wrapper}.exe", pe_x86_64())
            add_zip_file(
                archive,
                f"{wrapper}/README.txt",
                self.readme if readme is None else readme,
            )
            add_zip_file(archive, f"{wrapper}/sample_quiz.txt", self.sample)
        return path

    def make_macos(self):
        wrapper = f"DLMS-{VERSION}-macos-arm64"
        path = self.root / f"{wrapper}.zip"
        plist = plistlib.dumps(
            {
                "CFBundleExecutable": "DLMS",
                "CFBundleShortVersionString": VERSION,
                "CFBundleVersion": VERSION,
            }
        )
        with zipfile.ZipFile(path, "w") as archive:
            add_zip_file(archive, f"{wrapper}/README.txt", self.readme)
            add_zip_file(archive, f"{wrapper}/sample_quiz.txt", self.sample)
            add_zip_file(
                archive,
                f"{wrapper}/DLMS.app/Contents/Info.plist",
                plist,
            )
            add_zip_file(
                archive,
                f"{wrapper}/DLMS.app/Contents/MacOS/DLMS",
                macho_arm64(),
                0o755,
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
        self.assertEqual(result.stdout.count("Created and verified:"), 6)
        self.assertEqual(before, fingerprints())
        macos_package = output / f"DLMS-{VERSION}-macos-arm64.zip"
        with zipfile.ZipFile(macos_package) as archive:
            symlink_name = (
                f"DLMS-{VERSION}-macos-arm64/"
                "DLMS.app/Contents/Frameworks/Current"
            )
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


if __name__ == "__main__":
    unittest.main()
