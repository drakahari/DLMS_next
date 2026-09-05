"""Package already-built DLMS artifacts into the six final download archives.

The input staging directory is read-only. Outputs are assembled in a temporary
directory, validated, and moved into a distinct output directory only after all
six packages pass validation. This tool never builds or modifies native files.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path

from verify_release_artifact import release_version, sha256_file, verify_artifact
from verify_release_package import expected_packages, verify_release_package


LINUX_PLATFORMS = (
    "fedora44-x86_64",
    "ubuntu24.04-x86_64",
    "ubuntu26.04-x86_64",
    "omarchy-quattro-x86_64",
)


def _add_tar_file(
    archive: tarfile.TarFile, source: Path, archive_name: str, mode: int
) -> None:
    info = tarfile.TarInfo(archive_name)
    info.size = source.stat().st_size
    info.mode = mode
    info.mtime = 0
    with source.open("rb") as handle:
        archive.addfile(info, handle)


def _package_linux(
    source: Path, destination: Path, wrapper: str, assets_dir: Path
) -> None:
    with tarfile.open(destination, "w:gz") as archive:
        directory = tarfile.TarInfo(wrapper)
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        directory.mtime = 0
        archive.addfile(directory)
        _add_tar_file(archive, source, f"{wrapper}/{wrapper}", 0o755)
        for name in ("README.txt", "sample_quiz.txt"):
            _add_tar_file(archive, assets_dir / name, f"{wrapper}/{name}", 0o644)


def _zip_info_from_file(source: Path, archive_name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo.from_file(source, archive_name)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _write_zip_file(
    archive: zipfile.ZipFile, source: Path, archive_name: str, mode: int
) -> None:
    archive.writestr(
        _zip_info_from_file(source, archive_name, mode),
        source.read_bytes(),
    )


def _package_windows(
    source: Path, destination: Path, wrapper: str, assets_dir: Path
) -> None:
    with zipfile.ZipFile(destination, "w", allowZip64=True) as archive:
        _write_zip_file(archive, source, f"{wrapper}/{source.name}", 0o644)
        for name in ("README.txt", "sample_quiz.txt"):
            _write_zip_file(archive, assets_dir / name, f"{wrapper}/{name}", 0o644)


def _package_macos(source: Path, destination: Path) -> None:
    """Promote the verified app-only ZIP without changing a single archive byte.

    The native ``ditto --keepParent`` ZIP is already the final macOS
    distributable. Copying it byte-for-byte avoids both a second archive layout
    and any opportunity to alter bundle metadata, permissions, resource forks,
    or symbolic-link records on a non-macOS packaging host.
    """
    shutil.copyfile(source, destination)
    if sha256_file(source) != sha256_file(destination):
        raise OSError("macOS final distributable differs from its verified native ZIP")


def _input_artifacts(staging_dir: Path, version: str) -> list[tuple[str, Path, str]]:
    artifacts: list[tuple[str, Path, str]] = []
    for platform_name in LINUX_PLATFORMS:
        name = f"DLMS-{version}-{platform_name}"
        artifacts.append(("linux-x86_64", staging_dir / name, name + ".tar.gz"))
    windows = f"DLMS-{version}-windows11-x86_64.exe"
    artifacts.append(
        (
            "windows-x86_64",
            staging_dir / windows,
            windows.removesuffix(".exe") + ".zip",
        )
    )
    macos = f"DLMS-{version}-macos-arm64.zip"
    artifacts.append(("macos-arm64", staging_dir / macos, macos))
    return artifacts


def package_release(staging_dir: Path, output_dir: Path, source_root: Path) -> list[Path]:
    source_root = source_root.resolve()
    version = release_version(source_root)
    assets_dir = source_root / "release_assets"
    for name in ("README.txt", "sample_quiz.txt"):
        if not (assets_dir / name).is_file():
            raise ValueError(f"missing authoritative release asset: {assets_dir / name}")

    staging_dir = staging_dir.resolve()
    output_dir = output_dir.resolve()
    if staging_dir == output_dir or staging_dir in output_dir.parents:
        raise ValueError(
            "output directory must be outside the read-only staging directory"
        )
    artifacts = _input_artifacts(staging_dir, version)
    expected_output_names = set(expected_packages(version))
    if {output_name for _, _, output_name in artifacts} != expected_output_names:
        raise ValueError("internal final package set does not match release-package policy")

    for target, source, _ in artifacts:
        errors = verify_artifact(source, target, version)
        if errors:
            raise ValueError(f"invalid staged artifact {source.name}: {'; '.join(errors)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = [output_dir / output_name for _, _, output_name in artifacts]
    if any(path.exists() for path in existing):
        names = ", ".join(path.name for path in existing if path.exists())
        raise FileExistsError(f"refusing to overwrite existing final package(s): {names}")

    with tempfile.TemporaryDirectory(
        prefix=".dlms-package-", dir=output_dir
    ) as temporary:
        temporary_dir = Path(temporary)
        completed: list[Path] = []
        for target, source, output_name in artifacts:
            destination = temporary_dir / output_name
            spec = expected_packages(version)[output_name]
            if target == "linux-x86_64":
                _package_linux(source, destination, spec.wrapper, assets_dir)
            elif target == "windows-x86_64":
                _package_windows(source, destination, spec.wrapper, assets_dir)
            else:
                _package_macos(source, destination)
            errors = verify_release_package(destination, source_root)
            if errors:
                raise ValueError(f"invalid generated package {output_name}: {'; '.join(errors)}")
            completed.append(destination)

        final_paths: list[Path] = []
        for temporary_path in completed:
            final_path = output_dir / temporary_path.name
            os.replace(temporary_path, final_path)
            final_paths.append(final_path)
    return final_paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Package six already-built DLMS native artifacts."
    )
    parser.add_argument(
        "staging_dir", type=Path, help="read-only native artifact directory"
    )
    parser.add_argument(
        "output_dir", type=Path, help="distinct destination for final archives"
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root containing app.py and release_assets",
    )
    args = parser.parse_args()
    try:
        packages = package_release(args.staging_dir, args.output_dir, args.source_root)
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    for package in packages:
        print(f"Created and structurally verified final package: {package}")
    print("Native clean-extraction smoke is still required for every final package.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
