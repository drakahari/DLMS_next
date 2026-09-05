"""Verify exact final DLMS downloadable archives and optionally smoke them.

This complements ``verify_release_artifact.py``. Native artifacts must pass that
tool and native smoke/UAT before packaging; this tool verifies the small public
package created from each already-built artifact. ``--smoke`` clean-extracts one
final archive with the native platform's normal tooling and launches the
extracted executable, so an intermediate artifact cannot stand in for the file
users actually download.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import stat
import struct
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from verify_release_artifact import (
    MACOS_DITTO,
    RUNTIME_DATA_NAMES,
    _assert_smoke_host,
    _linux_machine,
    _macos_bundle_versions,
    _macos_cpu_types,
    _manifest_entries,
    _windows_machine,
    release_version,
    sha256_file,
    smoke_test_executable,
)


@dataclass(frozen=True)
class PackageSpec:
    kind: str
    target: str
    wrapper: str | None
    executable: str


FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    ".venv-build",
    "__pycache__",
    "backups",
    "build",
    "dist",
    "results.db",
    "uploads",
} | RUNTIME_DATA_NAMES
WINDOWS_POWERSHELL = (
    Path(os.environ.get("SystemRoot", r"C:\Windows"))
    / "System32"
    / "WindowsPowerShell"
    / "v1.0"
    / "powershell.exe"
)


def expected_packages(version: str) -> dict[str, PackageSpec]:
    prefix = f"DLMS-{version}-"
    specs: dict[str, PackageSpec] = {}
    for platform_name in (
        "fedora44-x86_64",
        "ubuntu24.04-x86_64",
        "ubuntu26.04-x86_64",
        "omarchy-quattro-x86_64",
    ):
        wrapper = prefix + platform_name
        specs[wrapper + ".tar.gz"] = PackageSpec(
            "linux", "linux-x86_64", wrapper, wrapper
        )

    wrapper = prefix + "windows11-x86_64"
    specs[wrapper + ".zip"] = PackageSpec(
        "windows", "windows-x86_64", wrapper, wrapper + ".exe"
    )

    name = prefix + "macos-arm64.zip"
    specs[name] = PackageSpec("macos", "macos-arm64", None, "DLMS.app")
    return specs


def _normalized_member_name(name: str) -> str:
    if not name or "\\" in name or name.startswith("/"):
        raise ValueError(f"unsafe archive member path: {name!r}")
    normalized = name.rstrip("/")
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe archive member path: {name!r}")
    return "/".join(parts)


def _check_common_names(
    names: list[str], required_root: str, *, check_duplicates: bool = True
) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for name in names:
        folded = name.casefold()
        if check_duplicates and folded in seen:
            errors.append(
                f"case-colliding or duplicate members: {seen[folded]} and {name}"
            )
        else:
            seen[folded] = name
        if PurePosixPath(name).parts[0] != required_root:
            errors.append(
                f"member is outside the required {required_root}/ root: {name}"
            )
        parts = {part.casefold() for part in PurePosixPath(name).parts}
        if parts.intersection(FORBIDDEN_PARTS):
            errors.append(f"forbidden development or runtime content: {name}")
        if name.casefold().endswith((".db", ".log")):
            errors.append(f"forbidden database or log file: {name}")
    return errors


def _elf_x86_64(binary: bytes) -> bool:
    if len(binary) < 20 or binary[:4] != b"\x7fELF" or binary[4] != 2:
        return False
    byte_order = "<" if binary[5] == 1 else ">" if binary[5] == 2 else None
    return byte_order is not None and struct.unpack(f"{byte_order}H", binary[18:20])[0] == 62


def _pe_x86_64(binary: bytes) -> bool:
    if len(binary) < 0x40 or binary[:2] != b"MZ":
        return False
    offset = struct.unpack("<I", binary[0x3C:0x40])[0]
    return (
        len(binary) >= offset + 6
        and binary[offset:offset + 4] == b"PE\0\0"
        and struct.unpack("<H", binary[offset + 4:offset + 6])[0] == 0x8664
    )


def _expected_asset_bytes(assets_dir: Path) -> tuple[dict[str, bytes], list[str]]:
    expected: dict[str, bytes] = {}
    errors: list[str] = []
    for name in ("README.txt", "sample_quiz.txt"):
        path = assets_dir / name
        try:
            expected[name] = path.read_bytes()
        except OSError as exc:
            errors.append(f"could not read authoritative {path}: {exc}")
    return expected, errors


def _verify_linux_package(
    package: Path, spec: PackageSpec, expected_assets: dict[str, bytes]
) -> list[str]:
    assert spec.wrapper is not None
    errors: list[str] = []
    expected_files = {
        f"{spec.wrapper}/{spec.executable}",
        f"{spec.wrapper}/README.txt",
        f"{spec.wrapper}/sample_quiz.txt",
    }
    try:
        with tarfile.open(package, "r:gz") as archive:
            files: dict[str, tarfile.TarInfo] = {}
            directories: list[str] = []
            names: list[str] = []
            for member in archive.getmembers():
                try:
                    name = _normalized_member_name(member.name)
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                names.append(name)
                if member.isdir():
                    directories.append(name)
                elif member.isfile():
                    files[name] = member
                else:
                    errors.append(f"unexpected non-file archive member: {name}")

            errors.extend(_check_common_names(names, spec.wrapper))
            if set(directories) - {spec.wrapper}:
                errors.append("Linux package contains unexpected directories")
            if set(files) != expected_files:
                missing = sorted(expected_files - set(files))
                extra = sorted(set(files) - expected_files)
                if missing:
                    errors.append(f"Linux package is missing: {', '.join(missing)}")
                if extra:
                    errors.append(
                        f"Linux package contains extra files: {', '.join(extra)}"
                    )

            executable_name = f"{spec.wrapper}/{spec.executable}"
            executable = files.get(executable_name)
            if executable is not None:
                if not executable.mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                    errors.append(
                        "Linux executable does not retain an execute permission bit"
                    )
                extracted = archive.extractfile(executable)
                if extracted is None or not _elf_x86_64(extracted.read(64)):
                    errors.append("Linux package executable is not an x86_64 ELF file")

            for asset_name, expected in expected_assets.items():
                member = files.get(f"{spec.wrapper}/{asset_name}")
                if member is not None:
                    extracted = archive.extractfile(member)
                    if extracted is None or extracted.read() != expected:
                        errors.append(
                            f"packaged {asset_name} does not match "
                            f"release_assets/{asset_name}"
                        )
    except (OSError, tarfile.TarError) as exc:
        errors.append(f"could not inspect tar.gz package: {exc}")
    return errors


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16)


def _macos_symlink_target_is_safe(name: str, target: bytes) -> bool:
    try:
        target_text = target.decode("utf-8")
    except UnicodeDecodeError:
        return False
    target_path = PurePosixPath(target_text)
    if not target_text or target_path.is_absolute() or "\\" in target_text:
        return False
    resolved = list(PurePosixPath(name).parent.parts)
    for part in target_path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if len(resolved) <= 1:
                return False
            resolved.pop()
        else:
            resolved.append(part)
    return bool(resolved) and resolved[0] == "DLMS.app"


def _verify_windows_package(
    archive: zipfile.ZipFile,
    infos: dict[str, zipfile.ZipInfo],
    spec: PackageSpec,
    expected_assets: dict[str, bytes],
) -> list[str]:
    assert spec.wrapper is not None
    errors: list[str] = []
    expected_files = {
        f"{spec.wrapper}/{spec.executable}",
        f"{spec.wrapper}/README.txt",
        f"{spec.wrapper}/sample_quiz.txt",
    }
    files = {name for name, info in infos.items() if not info.is_dir()}
    directories = {name for name, info in infos.items() if info.is_dir()}
    if directories - {spec.wrapper}:
        errors.append("Windows package contains unexpected directories")
    if files != expected_files:
        missing = sorted(expected_files - files)
        extra = sorted(files - expected_files)
        if missing:
            errors.append(f"Windows package is missing: {', '.join(missing)}")
        if extra:
            errors.append(f"Windows package contains extra files: {', '.join(extra)}")
    if any(_zip_member_is_symlink(info) for info in infos.values()):
        errors.append("Windows package must not contain symbolic links")

    executable_name = f"{spec.wrapper}/{spec.executable}"
    if executable_name in infos and not _pe_x86_64(archive.read(executable_name)):
        errors.append("Windows package executable is not an x86_64 PE file")
    for asset_name, expected in expected_assets.items():
        member_name = f"{spec.wrapper}/{asset_name}"
        if member_name in infos and archive.read(member_name) != expected:
            errors.append(
                f"packaged {asset_name} does not match release_assets/{asset_name}"
            )
    return errors


def _verify_macos_package(
    archive: zipfile.ZipFile,
    infos: dict[str, zipfile.ZipInfo],
    version: str,
) -> list[str]:
    errors: list[str] = []
    app_prefix = "DLMS.app/"
    required = {
        app_prefix + "Contents/Info.plist",
        app_prefix + "Contents/MacOS/DLMS",
    }
    files = {name for name, info in infos.items() if not info.is_dir()}
    for name in sorted(required - files):
        errors.append(f"macOS package is missing: {name}")
    for name in files:
        if name in required or name.startswith(app_prefix):
            continue
        errors.append("macOS package contains a file outside DLMS.app: " + name)

    if not any(name.startswith(app_prefix + "Contents/Resources/") for name in infos):
        errors.append("macOS package is missing bundled Resources content")

    plist_name = app_prefix + "Contents/Info.plist"
    if plist_name in infos:
        try:
            metadata = plistlib.loads(archive.read(plist_name))
            expected_versions = _macos_bundle_versions(version)
            if expected_versions is None:
                errors.append("APP_VERSION is not compatible with macOS bundle metadata")
            else:
                short_version, build_version = expected_versions
                if metadata.get("CFBundleShortVersionString") != short_version:
                    errors.append("macOS CFBundleShortVersionString does not match APP_VERSION")
                if metadata.get("CFBundleVersion") != build_version:
                    errors.append("macOS CFBundleVersion does not match APP_VERSION")
                if metadata.get("CFBundleExecutable") != "DLMS":
                    errors.append("macOS CFBundleExecutable is not DLMS")
                if metadata.get("CFBundleIdentifier") != "io.github.drakahari.DLMS":
                    errors.append("macOS CFBundleIdentifier is not io.github.drakahari.DLMS")
        except (plistlib.InvalidFileException, ValueError) as exc:
            errors.append(f"could not parse macOS Info.plist: {exc}")

    executable_name = app_prefix + "Contents/MacOS/DLMS"
    executable = infos.get(executable_name)
    if executable is not None:
        mode = executable.external_attr >> 16
        if executable.create_system == 3 and not mode & (
            stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        ):
            errors.append("macOS bundle executable does not retain an execute permission bit")
        if 0x0100000C not in _macos_cpu_types(archive.read(executable_name)):
            errors.append("macOS bundle executable is not an arm64 Mach-O binary")
    for name, info in infos.items():
        if _zip_member_is_symlink(info) and not _macos_symlink_target_is_safe(
            name, archive.read(info)
        ):
            errors.append(f"macOS bundle symlink escapes DLMS.app or is invalid: {name}")
    return errors


def verify_release_package(package: Path, source_root: Path) -> list[str]:
    errors: list[str] = []
    try:
        version = release_version(source_root)
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"could not determine release version: {exc}"]
    spec = expected_packages(version).get(package.name)
    if spec is None:
        return [f"unexpected final package filename: {package.name}"]
    if not package.is_file():
        return [f"package does not exist: {package}"]

    expected_assets: dict[str, bytes] = {}
    if spec.kind != "macos":
        expected_assets, asset_errors = _expected_asset_bytes(
            source_root / "release_assets"
        )
        errors.extend(asset_errors)
        if asset_errors:
            return errors
    if spec.kind == "linux":
        return _verify_linux_package(package, spec, expected_assets)

    try:
        with zipfile.ZipFile(package) as archive:
            infos: dict[str, zipfile.ZipInfo] = {}
            names: list[str] = []
            metadata_names: list[str] = []
            seen_names: dict[str, str] = {}
            for info in archive.infolist():
                try:
                    name = _normalized_member_name(info.filename)
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                folded = name.casefold()
                if folded in seen_names:
                    errors.append(
                        "case-colliding or duplicate members: "
                        f"{seen_names[folded]} and {name}"
                    )
                else:
                    seen_names[folded] = name
                if name == "__MACOSX" or name.startswith("__MACOSX/"):
                    metadata_names.append(name)
                    continue
                names.append(name)
                infos[name] = info
            required_root = "DLMS.app" if spec.kind == "macos" else spec.wrapper
            assert required_root is not None
            errors.extend(
                _check_common_names(names, required_root, check_duplicates=False)
            )
            if metadata_names:
                if spec.kind != "macos":
                    errors.append("non-macOS package contains __MACOSX metadata")
                else:
                    allowed_metadata = {"__MACOSX", "__MACOSX/DLMS.app"}
                    for name in metadata_names:
                        if (
                            name not in allowed_metadata
                            and name != "__MACOSX/._DLMS.app"
                            and not name.startswith("__MACOSX/DLMS.app/")
                        ):
                            errors.append(f"unexpected macOS metadata path: {name}")
            if spec.kind == "windows":
                errors.extend(_verify_windows_package(archive, infos, spec, expected_assets))
            else:
                errors.extend(
                    _verify_macos_package(archive, infos, version)
                )
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        errors.append(f"could not inspect ZIP package: {exc}")
    return errors


def _extract_final_package(
    package: Path, spec: PackageSpec, extraction_root: Path
) -> None:
    """Clean-extract one structurally verified final distributable."""
    extraction_root.mkdir(parents=True, exist_ok=False)
    if spec.kind == "linux":
        with tarfile.open(package, "r:gz") as archive:
            archive.extractall(extraction_root, filter="data")
        return
    if spec.kind == "macos":
        if not MACOS_DITTO.is_file():
            raise RuntimeError("macOS ditto is required for final app-bundle extraction")
        command = [
            str(MACOS_DITTO),
            "-x",
            "-k",
            str(package),
            str(extraction_root),
        ]
        environment = None
    else:
        if not WINDOWS_POWERSHELL.is_file():
            raise RuntimeError(
                "Windows PowerShell is required for final ZIP extraction"
            )
        command = [
            str(WINDOWS_POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "Expand-Archive -LiteralPath $env:DLMS_RELEASE_ARCHIVE "
                "-DestinationPath $env:DLMS_RELEASE_DESTINATION -Force"
            ),
        ]
        environment = os.environ.copy()
        environment["DLMS_RELEASE_ARCHIVE"] = str(package)
        environment["DLMS_RELEASE_DESTINATION"] = str(extraction_root)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail[-1200:]}" if detail else ""
        raise RuntimeError(
            f"{spec.kind} final-package extraction failed "
            f"(exit code {result.returncode}){suffix}"
        )


def _verify_extracted_macos(
    package: Path, extraction_root: Path, version: str
) -> tuple[Path, list[str]]:
    errors: list[str] = []
    app = extraction_root / "DLMS.app"
    executable = app / "Contents" / "MacOS" / "DLMS"
    plist = app / "Contents" / "Info.plist"
    resources = app / "Contents" / "Resources"
    if not app.is_dir():
        errors.append("clean extraction did not produce root-level DLMS.app")
    if not executable.is_file():
        errors.append("clean extraction is missing DLMS.app/Contents/MacOS/DLMS")
    else:
        if not os.access(executable, os.X_OK):
            errors.append("clean-extracted macOS executable is not executable")
        if 0x0100000C not in _macos_cpu_types(executable.read_bytes()):
            errors.append("clean-extracted macOS executable is not arm64 Mach-O")
    if not resources.is_dir():
        errors.append("clean extraction is missing DLMS.app/Contents/Resources")
    if not plist.is_file():
        errors.append("clean extraction is missing DLMS.app/Contents/Info.plist")
    else:
        try:
            metadata = plistlib.loads(plist.read_bytes())
            expected_versions = _macos_bundle_versions(version)
            if expected_versions is None:
                errors.append("APP_VERSION is not compatible with macOS bundle metadata")
            else:
                short_version, build_version = expected_versions
                if metadata.get("CFBundleShortVersionString") != short_version:
                    errors.append(
                        "clean-extracted macOS CFBundleShortVersionString does not match APP_VERSION"
                    )
                if metadata.get("CFBundleVersion") != build_version:
                    errors.append(
                        "clean-extracted macOS CFBundleVersion does not match APP_VERSION"
                    )
            if metadata.get("CFBundleExecutable") != "DLMS":
                errors.append("clean-extracted macOS CFBundleExecutable is not DLMS")
            if metadata.get("CFBundleIdentifier") != "io.github.drakahari.DLMS":
                errors.append(
                    "clean-extracted macOS CFBundleIdentifier is not io.github.drakahari.DLMS"
                )
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            errors.append(f"could not parse clean-extracted macOS Info.plist: {exc}")

    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            name = info.filename.rstrip("/")
            if name.startswith("DLMS.app/") and _zip_member_is_symlink(info):
                if not (extraction_root / name).is_symlink():
                    errors.append(f"clean extraction did not preserve bundle symlink: {name}")
    return executable, errors


def verify_extracted_release_package(
    package: Path,
    extraction_root: Path,
    spec: PackageSpec,
    source_root: Path,
) -> tuple[Path, list[str]]:
    """Validate filesystem results after the user's final archive is extracted."""
    version = release_version(source_root)
    expected_top = "DLMS.app" if spec.kind == "macos" else spec.wrapper
    assert expected_top is not None
    actual_top = {path.name for path in extraction_root.iterdir()}
    errors: list[str] = []
    if actual_top != {expected_top}:
        errors.append(
            "clean extraction must contain exactly one top-level "
            f"{expected_top}; got {', '.join(sorted(actual_top)) or 'nothing'}"
        )

    if spec.kind == "macos":
        executable, platform_errors = _verify_extracted_macos(
            package, extraction_root, version
        )
        errors.extend(platform_errors)
        return executable, errors

    assert spec.wrapper is not None
    package_root = extraction_root / spec.wrapper
    executable = package_root / spec.executable
    expected_assets, asset_errors = _expected_asset_bytes(
        source_root / "release_assets"
    )
    errors.extend(asset_errors)
    if not package_root.is_dir():
        errors.append(f"clean extraction is missing wrapper directory {spec.wrapper}")
        return executable, errors
    expected_files = {spec.executable, "README.txt", "sample_quiz.txt"}
    actual_files = {path.name for path in package_root.iterdir() if path.is_file()}
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        if missing:
            errors.append("clean extraction is missing: " + ", ".join(missing))
        if extra:
            errors.append("clean extraction contains extra files: " + ", ".join(extra))
    if any(path.is_dir() for path in package_root.iterdir()):
        errors.append("clean extraction contains an unexpected subdirectory")
    for asset_name, expected in expected_assets.items():
        asset = package_root / asset_name
        if asset.is_file() and asset.read_bytes() != expected:
            errors.append(
                f"clean-extracted {asset_name} does not match release_assets/{asset_name}"
            )
    if executable.is_file():
        if spec.kind == "linux":
            if not os.access(executable, os.X_OK):
                errors.append("clean-extracted Linux executable is not executable")
            if _linux_machine(executable) != 62:
                errors.append("clean-extracted Linux executable is not x86_64 ELF")
        elif _windows_machine(executable) != 0x8664:
            errors.append("clean-extracted Windows executable is not x86_64 PE")
    else:
        errors.append(f"clean extraction is missing executable {spec.executable}")
    return executable, errors


def clean_extract_and_smoke(package: Path, source_root: Path) -> list[str]:
    """Validate and smoke the executable from the exact final archive bytes."""
    version = release_version(source_root)
    spec = expected_packages(version).get(package.name)
    if spec is None:
        return [f"unexpected final package filename: {package.name}"]
    errors = verify_release_package(package, source_root)
    if errors:
        return errors
    try:
        _assert_smoke_host(spec.target)
        with tempfile.TemporaryDirectory(
            prefix="dlms-final-package-extraction-"
        ) as temporary:
            extraction_root = Path(temporary) / "extracted"
            _extract_final_package(package, spec, extraction_root)
            executable, extraction_errors = verify_extracted_release_package(
                package, extraction_root, spec, source_root
            )
            if extraction_errors:
                return extraction_errors
            smoke_test_executable(executable, spec.target)
    except (OSError, RuntimeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        return [f"final-package extraction/smoke failed: {exc}"]
    return []


def _verify_manifest(packages: list[Path], manifest: Path) -> list[str]:
    try:
        entries = _manifest_entries(manifest)
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"could not read checksum manifest: {exc}"]
    errors: list[str] = []
    if list(entries) != sorted(entries):
        errors.append("checksum manifest entries are not sorted by filename")
    package_names = {path.name for path in packages}
    if set(entries) != package_names:
        missing = sorted(package_names - set(entries))
        extra = sorted(set(entries) - package_names)
        if missing:
            errors.append(f"checksum manifest is missing: {', '.join(missing)}")
        if extra:
            errors.append(
                f"checksum manifest contains unexpected files: {', '.join(extra)}"
            )
        return errors
    for package in packages:
        actual = sha256_file(package)
        if entries[package.name] != actual:
            errors.append(f"SHA256 mismatch for {package.name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify final DLMS downloadable package contents."
    )
    parser.add_argument("packages", nargs="+", type=Path)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root containing app.py and release_assets",
    )
    parser.add_argument("--checksums", type=Path, help="final SHA256SUMS.txt")
    parser.add_argument(
        "--complete-set",
        action="store_true",
        help="require exactly the six supported DLMS release packages",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=(
            "clean-extract one final archive with native platform tooling and "
            "smoke-test its extracted executable"
        ),
    )
    args = parser.parse_args()
    if args.smoke and len(args.packages) != 1:
        parser.error("--smoke requires exactly one final package")

    version = release_version(args.source_root)
    expected = set(expected_packages(version))
    supplied = {path.name for path in args.packages}
    errors: list[str] = []
    if len(supplied) != len(args.packages):
        errors.append("each package filename must be supplied only once")
    if args.complete_set and supplied != expected:
        missing = sorted(expected - supplied)
        extra = sorted(supplied - expected)
        if missing:
            errors.append(f"final package set is missing: {', '.join(missing)}")
        if extra:
            errors.append(f"final package set contains unexpected files: {', '.join(extra)}")

    for package in args.packages:
        package_errors = verify_release_package(package, args.source_root)
        if package_errors:
            errors.extend(f"{package.name}: {error}" for error in package_errors)
        else:
            print(f"Verified release package: {package.name}")
            if args.smoke:
                smoke_errors = clean_extract_and_smoke(
                    package.resolve(), args.source_root.resolve()
                )
                if smoke_errors:
                    errors.extend(
                        f"{package.name}: {error}" for error in smoke_errors
                    )
                else:
                    print(
                        "Clean extraction and native smoke passed: "
                        f"{package.name}"
                    )
    if args.checksums:
        errors.extend(_verify_manifest(args.packages, args.checksums))

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    if args.checksums:
        print(f"Verified checksum manifest: {args.checksums}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
