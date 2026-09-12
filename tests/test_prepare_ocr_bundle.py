"""Regression coverage for native OCR bundle preparation tooling."""

import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import prepare_ocr_bundle as preparation
from tools.pyinstaller_ocr import validate_tesseract_bundle


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, contents: bytes = b"fixture") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return path


def _source_tree(root: Path, *, executable=True):
    binary = _write(root / "source" / "bin" / "tesseract", b"native executable")
    binary.chmod(0o755 if executable else 0o644)
    library = _write(
        root / "source" / "bin" / "libtesseract.so.5", b"native library"
    )
    tessdata = root / "source" / "tessdata"
    _write(tessdata / "eng.traineddata", b"english model")
    _write(tessdata / "configs" / "tsv", b"tessedit_create_tsv 1\n")
    licenses = []
    for name in ("tesseract", "tessdata", "leptonica"):
        licenses.append(
            _write(
                root / "source" / "licenses" / f"{name}.txt",
                f"{name} license".encode(),
            )
        )
    sources = preparation.BundleSources(
        platform_name="linux",
        executable=binary,
        tessdata_dir=tessdata,
        tesseract_license=licenses[0],
        tessdata_license=licenses[1],
        leptonica_license=licenses[2],
    )
    return sources, library


class OCRBundlePreparationTests(unittest.TestCase):
    def test_platform_detection_is_explicit(self):
        self.assertEqual(preparation.detect_platform("Linux"), "linux")
        self.assertEqual(preparation.detect_platform("Darwin"), "macos")
        self.assertEqual(preparation.detect_platform("Windows"), "windows")
        self.assertEqual(preparation.detect_platform("win32"), "windows")
        with self.assertRaisesRegex(ValueError, "Unsupported OCR bundle platform"):
            preparation.detect_platform("Plan9")
        with mock.patch.object(preparation.platform, "system", return_value="Darwin"):
            self.assertEqual(preparation.detect_platform(), "macos")

    def test_ubuntu_package_paths_are_discovered_through_injected_root(self):
        with tempfile.TemporaryDirectory(prefix="dlms-ocr-discovery-") as directory:
            root = Path(directory)
            executable = _write(root / "usr/bin/tesseract", b"native")
            executable.chmod(0o755)
            tessdata = root / "usr/share/tesseract-ocr/5/tessdata"
            _write(tessdata / "eng.traineddata", b"model")
            _write(tessdata / "configs/tsv", b"config")
            tesseract_license = _write(
                root / "usr/share/doc/tesseract-ocr/copyright", b"tesseract"
            )
            tessdata_license = _write(
                root / "usr/share/doc/tesseract-ocr-eng/copyright", b"tessdata"
            )
            leptonica_license = _write(
                root / "usr/share/doc/libleptonica6/copyright", b"leptonica"
            )

            sources = preparation.discover_bundle_sources(
                "linux",
                filesystem_root=root,
                which=lambda name: str(executable) if name == "tesseract" else None,
                cache_root=root / "cache",
            )

            self.assertEqual(sources.executable, executable.resolve())
            self.assertEqual(sources.tessdata_dir, tessdata.resolve())
            self.assertEqual(sources.tesseract_license, tesseract_license.resolve())
            self.assertEqual(sources.tessdata_license, tessdata_license.resolve())
            self.assertEqual(sources.leptonica_license, leptonica_license.resolve())

    def test_homebrew_prefixes_are_discoverable_without_fixed_versions(self):
        with tempfile.TemporaryDirectory(prefix="dlms-ocr-homebrew-") as directory:
            root = Path(directory)
            tesseract_prefix = root / "Cellar" / "tesseract" / "future-version"
            leptonica_prefix = root / "Cellar" / "leptonica" / "future-version"
            executable = _write(tesseract_prefix / "bin/tesseract", b"native")
            executable.chmod(0o755)
            tessdata = tesseract_prefix / "share/tessdata"
            _write(tessdata / "eng.traineddata", b"model")
            _write(tessdata / "configs/tsv", b"config")
            tesseract_license = _write(tesseract_prefix / "LICENSE", b"tesseract")
            tessdata_license = _write(root / "tessdata-LICENSE", b"tessdata")
            leptonica_license = _write(
                leptonica_prefix / "leptonica-license.txt", b"leptonica"
            )

            sources = preparation.discover_bundle_sources(
                "macos",
                which=lambda _name: None,
                brew_prefix=lambda formula: (
                    tesseract_prefix if formula == "tesseract" else leptonica_prefix
                ),
                tessdata_license=tessdata_license,
                cache_root=root / "cache",
            )

            self.assertEqual(sources.executable, executable.resolve())
            self.assertEqual(sources.tessdata_dir, tessdata.resolve())
            self.assertEqual(sources.tesseract_license, tesseract_license.resolve())
            self.assertEqual(sources.leptonica_license, leptonica_license.resolve())

    def test_discovery_rejects_missing_english_data_or_tsv_config(self):
        for missing in ("eng.traineddata", "configs/tsv"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory(
                prefix="dlms-ocr-missing-data-"
            ) as directory:
                root = Path(directory)
                executable = _write(root / "tesseract", b"native")
                executable.chmod(0o755)
                tessdata = root / "tessdata"
                if missing != "eng.traineddata":
                    _write(tessdata / "eng.traineddata", b"model")
                if missing != "configs/tsv":
                    _write(tessdata / "configs/tsv", b"config")
                with self.assertRaisesRegex(ValueError, "Missing or empty tessdata"):
                    preparation.discover_bundle_sources(
                        "linux",
                        executable=executable,
                        tessdata_dir=tessdata,
                        tesseract_license=root / "missing-tesseract-license",
                        tessdata_license=root / "missing-tessdata-license",
                        leptonica_license=root / "missing-leptonica-license",
                        cache_root=root / "cache",
                    )

    def test_explicit_missing_license_is_not_replaced_silently(self):
        with tempfile.TemporaryDirectory(
            prefix="dlms-ocr-license-"
        ) as directory:
            root = Path(directory)
            sources, _library = _source_tree(root)
            with self.assertRaisesRegex(ValueError, "tessdata license"):
                preparation.discover_bundle_sources(
                    "linux",
                    executable=sources.executable,
                    tessdata_dir=sources.tessdata_dir,
                    tesseract_license=sources.tesseract_license,
                    tessdata_license=root / "missing-license",
                    leptonica_license=sources.leptonica_license,
                    cache_root=root / "cache",
                )

    def test_official_license_download_is_hash_checked_and_cached(self):
        payload = b"pinned upstream license\n"
        definition = {
            "url": "https://licenses.invalid/immutable/license.txt",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        with tempfile.TemporaryDirectory(
            prefix="dlms-ocr-license-cache-"
        ) as directory, mock.patch.dict(
            preparation.OFFICIAL_LICENSES, {"leptonica": definition}
        ):
            cache = Path(directory)
            downloader = mock.Mock(return_value=payload)
            first = preparation._cached_official_license(
                "leptonica", cache, allow_download=True, downloader=downloader
            )
            second = preparation._cached_official_license(
                "leptonica",
                cache,
                allow_download=False,
                downloader=mock.Mock(side_effect=AssertionError("network used")),
            )

            self.assertEqual(first, second)
            self.assertEqual(first.read_bytes(), payload)
            downloader.assert_called_once_with(definition["url"])

    def test_download_with_wrong_checksum_is_rejected(self):
        with tempfile.TemporaryDirectory(
            prefix="dlms-ocr-license-cache-"
        ) as directory:
            with self.assertRaisesRegex(ValueError, "pinned SHA-256"):
                preparation._cached_official_license(
                    "leptonica",
                    Path(directory),
                    allow_download=True,
                    downloader=lambda _url: b"incorrect license",
                )

    def test_preparation_is_atomic_validated_and_does_not_mutate_sources(self):
        with tempfile.TemporaryDirectory(prefix="dlms-ocr-preparation-") as directory:
            root = Path(directory)
            sources, library = _source_tree(root)
            source_paths = (
                sources.executable,
                library,
                sources.tessdata_dir / "eng.traineddata",
                sources.tessdata_dir / "configs/tsv",
                sources.tesseract_license,
                sources.tessdata_license,
                sources.leptonica_license,
            )
            before = {
                path: (
                    path.read_bytes(),
                    stat.S_IMODE(path.stat().st_mode),
                    path.stat().st_mtime_ns,
                )
                for path in source_paths
            }
            output = root / "output" / ".ocr-bundle"

            prepared = preparation.prepare_bundle(sources, output)

            self.assertEqual(prepared, output.resolve())
            validate_tesseract_bundle(prepared, platform_name="linux")
            self.assertTrue((prepared / "bin/libtesseract.so.5").is_file())
            after = {
                path: (
                    path.read_bytes(),
                    stat.S_IMODE(path.stat().st_mode),
                    path.stat().st_mtime_ns,
                )
                for path in source_paths
            }
            self.assertEqual(before, after)
            self.assertFalse(list(output.parent.glob(".*-preparing-*")))

    def test_windows_preparation_uses_exe_and_copies_adjacent_dll(self):
        with tempfile.TemporaryDirectory(prefix="dlms-ocr-windows-") as directory:
            root = Path(directory)
            source_root = root / "source"
            executable = _write(source_root / "bin/tesseract.exe", b"windows exe")
            library = _write(source_root / "bin/liblept.dll", b"windows dll")
            tessdata = source_root / "tessdata"
            _write(tessdata / "eng.traineddata", b"english model")
            _write(tessdata / "configs/tsv", b"tsv config")
            licenses = [
                _write(source_root / "licenses" / f"{name}.txt", name.encode())
                for name in ("tesseract", "tessdata", "leptonica")
            ]
            sources = preparation.BundleSources(
                platform_name="windows",
                executable=executable,
                tessdata_dir=tessdata,
                tesseract_license=licenses[0],
                tessdata_license=licenses[1],
                leptonica_license=licenses[2],
            )

            output = preparation.prepare_bundle(sources, root / ".ocr-bundle")

            paths = validate_tesseract_bundle(output, platform_name="windows")
            self.assertEqual(paths["executable"].name, "tesseract.exe")
            self.assertEqual(
                (output / "bin/liblept.dll").read_bytes(), library.read_bytes()
            )

    @unittest.skipIf(os.name == "nt", "POSIX execute bits do not apply on Windows")
    def test_non_executable_tesseract_is_rejected_without_publishing_output(self):
        with tempfile.TemporaryDirectory(prefix="dlms-ocr-nonexec-") as directory:
            root = Path(directory)
            sources, _library = _source_tree(root, executable=False)
            output = root / ".ocr-bundle"

            with self.assertRaisesRegex(ValueError, "not executable"):
                preparation.prepare_bundle(sources, output)

            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob(".*-preparing-*")))

    def test_repository_output_must_be_git_ignored(self):
        rejected = mock.Mock(return_value=subprocess.CompletedProcess([], 1))
        with self.assertRaisesRegex(ValueError, "must be ignored by Git"):
            preparation.ensure_local_only_output(
                ROOT / "not-ignored-ocr-bundle", ROOT, runner=rejected
            )
        checked_path = rejected.call_args.args[0][-1]
        self.assertEqual(
            checked_path,
            "not-ignored-ocr-bundle/.dlms-ocr-bundle-check",
        )


if __name__ == "__main__":
    unittest.main()
