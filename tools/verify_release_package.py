"""Verify final DLMS downloadable archives without extracting them.

This complements ``verify_release_artifact.py``. Native artifacts must pass that
tool and native smoke/UAT before packaging; this tool verifies the small public
package wrapped around each already-built artifact.
"""

from __future__ import annotations

import argparse
import plistlib
import stat
import struct
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from verify_release_artifact import (
    RUNTIME_DATA_NAMES,
    _macos_bundle_versions,
    _macos_cpu_types,
    _manifest_entries,
    release_version,
    sha256_file,
)


@dataclass(frozen=True)
class PackageSpec:
    kind: str
    wrapper: str
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
        specs[wrapper + ".tar.gz"] = PackageSpec("linux", wrapper, wrapper)

    wrapper = prefix + "windows11-x86_64"
    specs[wrapper + ".zip"] = PackageSpec("windows", wrapper, wrapper + ".exe")

    wrapper = prefix + "macos-arm64"
    specs[wrapper + ".zip"] = PackageSpec("macos", wrapper, "DLMS.app")
    return specs


def _normalized_member_name(name: str) -> str:
    if not name or "\\" in name or name.startswith("/"):
        raise ValueError(f"unsafe archive member path: {name!r}")
    normalized = name.rstrip("/")
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe archive member path: {name!r}")
    return "/".join(parts)


def _check_common_names(names: list[str], wrapper: str) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for name in names:
        folded = name.casefold()
        if folded in seen:
            errors.append(
                f"case-colliding or duplicate members: {seen[folded]} and {name}"
            )
        else:
            seen[folded] = name
        if PurePosixPath(name).parts[0] != wrapper:
            errors.append(f"member is outside the required {wrapper}/ folder: {name}")
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


def _verify_windows_package(
    archive: zipfile.ZipFile,
    infos: dict[str, zipfile.ZipInfo],
    spec: PackageSpec,
    expected_assets: dict[str, bytes],
) -> list[str]:
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
    spec: PackageSpec,
    expected_assets: dict[str, bytes],
    version: str,
) -> list[str]:
    errors: list[str] = []
    app_prefix = f"{spec.wrapper}/DLMS.app/"
    required = {
        f"{spec.wrapper}/README.txt",
        f"{spec.wrapper}/sample_quiz.txt",
        app_prefix + "Contents/Info.plist",
        app_prefix + "Contents/MacOS/DLMS",
    }
    files = {name for name, info in infos.items() if not info.is_dir()}
    for name in sorted(required - files):
        errors.append(f"macOS package is missing: {name}")
    for name in files:
        if name in required or name.startswith(app_prefix):
            continue
        errors.append(
            "macOS package contains a file outside DLMS.app and release documents: "
            + name
        )

    for asset_name, expected in expected_assets.items():
        member_name = f"{spec.wrapper}/{asset_name}"
        if member_name in infos and archive.read(member_name) != expected:
            errors.append(
                f"packaged {asset_name} does not match release_assets/{asset_name}"
            )

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

    expected_assets, asset_errors = _expected_asset_bytes(source_root / "release_assets")
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
            for info in archive.infolist():
                try:
                    name = _normalized_member_name(info.filename)
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                if name == "__MACOSX" or name.startswith("__MACOSX/"):
                    metadata_names.append(name)
                    continue
                names.append(name)
                if name in infos:
                    errors.append(f"duplicate archive member: {name}")
                infos[name] = info
            errors.extend(_check_common_names(names, spec.wrapper))
            if metadata_names:
                if spec.kind != "macos":
                    errors.append("non-macOS package contains __MACOSX metadata")
                expected_metadata_prefix = f"__MACOSX/{spec.wrapper}/"
                for name in metadata_names:
                    allowed_roots = {"__MACOSX", f"__MACOSX/{spec.wrapper}"}
                    if name not in allowed_roots and not name.startswith(
                        expected_metadata_prefix
                    ):
                        errors.append(f"unexpected macOS metadata path: {name}")
            if spec.kind == "windows":
                errors.extend(_verify_windows_package(archive, infos, spec, expected_assets))
            else:
                errors.extend(
                    _verify_macos_package(
                        archive, infos, spec, expected_assets, version
                    )
                )
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        errors.append(f"could not inspect ZIP package: {exc}")
    return errors


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
    args = parser.parse_args()

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
