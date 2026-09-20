"""Package already-built DLMS artifacts into final download archives.

Single-target mode packages and optionally native-smokes one artifact on its
build host. Coordinated mode retains the six-artifact workflow. Inputs remain
read-only; outputs are assembled in a temporary directory, validated, and moved
into a distinct output directory only after the required gates pass. This tool
never builds or modifies native files.
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
from verify_release_package import (
    clean_extract_and_smoke,
    expected_packages,
    verify_release_package,
)


LINUX_PLATFORMS = (
    "fedora44-x86_64",
    "ubuntu24.04-x86_64",
    "ubuntu26.04-x86_64",
    "omarchy-quattro-x86_64",
)
RELEASE_TARGETS = LINUX_PLATFORMS + (
    "windows11-x86_64",
    "macos-arm64",
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


def _package_macos(source: Path, destination: Path, assets_dir: Path) -> None:
    """Add authoritative root documents to the verified native app ZIP."""
    shutil.copyfile(source, destination)
    if sha256_file(source) != sha256_file(destination):
        raise OSError("macOS staging copy differs from its verified native ZIP")
    with zipfile.ZipFile(destination, "a", allowZip64=True) as archive:
        for name in ("README.txt", "sample_quiz.txt"):
            _write_zip_file(archive, assets_dir / name, name, 0o644)


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


def _single_target_contract(target: str, version: str) -> tuple[str, str, str]:
    """Return verifier target, native artifact name, and final package name."""
    if target in LINUX_PLATFORMS:
        artifact_name = f"DLMS-{version}-{target}"
        return "linux-x86_64", artifact_name, artifact_name + ".tar.gz"
    if target == "windows11-x86_64":
        base = f"DLMS-{version}-{target}"
        return "windows-x86_64", base + ".exe", base + ".zip"
    if target == "macos-arm64":
        name = f"DLMS-{version}-{target}.zip"
        return "macos-arm64", name, name
    raise ValueError(f"unsupported release target: {target}")


def _release_assets(source_root: Path) -> Path:
    assets_dir = source_root / "release_assets"
    for name in ("README.txt", "sample_quiz.txt"):
        if not (assets_dir / name).is_file():
            raise ValueError(f"missing authoritative release asset: {assets_dir / name}")
    return assets_dir


def _assemble_package(
    source: Path,
    destination: Path,
    target: str,
    output_name: str,
    assets_dir: Path,
    version: str,
) -> None:
    spec = expected_packages(version)[output_name]
    if target == "linux-x86_64":
        assert spec.wrapper is not None
        _package_linux(source, destination, spec.wrapper, assets_dir)
    elif target == "windows-x86_64":
        assert spec.wrapper is not None
        _package_windows(source, destination, spec.wrapper, assets_dir)
    elif target == "macos-arm64":
        _package_macos(source, destination, assets_dir)
    else:
        raise ValueError(f"unsupported package assembly target: {target}")


def package_single_target(
    target: str,
    artifact: Path,
    output_dir: Path,
    source_root: Path,
    *,
    smoke: bool = False,
) -> Path:
    """Create, verify, and optionally native-smoke one final release package."""
    source_root = source_root.resolve()
    version = release_version(source_root)
    assets_dir = _release_assets(source_root)
    verifier_target, artifact_name, output_name = _single_target_contract(
        target, version
    )
    artifact = artifact.resolve()
    if artifact.name != artifact_name:
        raise ValueError(
            f"{target} requires canonical native artifact name "
            f"{artifact_name}; got {artifact.name}"
        )
    artifact_errors = verify_artifact(artifact, verifier_target, version)
    if artifact_errors:
        raise ValueError(
            f"invalid native artifact {artifact.name}: {'; '.join(artifact_errors)}"
        )

    output_dir = output_dir.resolve()
    if output_dir == artifact.parent:
        raise ValueError(
            "output directory must differ from the native artifact directory"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / output_name
    if final_path.exists():
        raise FileExistsError(
            f"refusing to overwrite existing final package: {final_path.name}"
        )

    with tempfile.TemporaryDirectory(
        prefix=".dlms-package-", dir=output_dir
    ) as temporary:
        temporary_path = Path(temporary) / output_name
        _assemble_package(
            artifact,
            temporary_path,
            verifier_target,
            output_name,
            assets_dir,
            version,
        )
        package_errors = verify_release_package(temporary_path, source_root)
        if package_errors:
            raise ValueError(
                f"invalid generated package {output_name}: "
                + "; ".join(package_errors)
            )
        if smoke:
            smoke_errors = clean_extract_and_smoke(temporary_path, source_root)
            if smoke_errors:
                raise ValueError(
                    f"final-package native smoke failed for {output_name}: "
                    + "; ".join(smoke_errors)
                )
        os.replace(temporary_path, final_path)
    return final_path


def package_release(staging_dir: Path, output_dir: Path, source_root: Path) -> list[Path]:
    source_root = source_root.resolve()
    version = release_version(source_root)
    assets_dir = _release_assets(source_root)

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
            _assemble_package(
                source, destination, target, output_name, assets_dir, version
            )
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
        description=(
            "Package one native DLMS artifact on its build host, or package "
            "the coordinated six-artifact release set."
        )
    )
    parser.add_argument(
        "staging_dir",
        nargs="?",
        type=Path,
        help="all-six mode: read-only native artifact directory",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        type=Path,
        help="all-six mode: distinct destination for final archives",
    )
    parser.add_argument(
        "--target",
        choices=RELEASE_TARGETS,
        help="single-target mode: exact native release target",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        help="single-target mode: canonical already-built native artifact",
    )
    parser.add_argument(
        "--output-dir",
        dest="single_output_dir",
        type=Path,
        help="single-target mode: distinct final-package directory",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="single-target mode: clean-extract and native-smoke the final archive",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root containing app.py and release_assets",
    )
    args = parser.parse_args()
    try:
        if args.target is not None:
            if args.staging_dir is not None or args.output_dir is not None:
                parser.error(
                    "single-target mode uses --artifact and --output-dir, not positional paths"
                )
            if args.artifact is None or args.single_output_dir is None:
                parser.error(
                    "--target requires both --artifact and --output-dir"
                )
            package = package_single_target(
                args.target,
                args.artifact,
                args.single_output_dir,
                args.source_root,
                smoke=args.smoke,
            )
            print(f"Created and verified final package: {package}")
            if args.smoke:
                print(f"Clean extraction and native smoke passed: {package.name}")
            print(f"SHA-256: {sha256_file(package)}  {package.name}")
            return 0

        if args.artifact is not None or args.single_output_dir is not None:
            parser.error("--artifact and --output-dir require --target")
        if args.smoke:
            parser.error("--smoke is available only with --target")
        if args.staging_dir is None or args.output_dir is None:
            parser.error(
                "all-six mode requires staging_dir and output_dir, or use --target"
            )
        packages = package_release(
            args.staging_dir, args.output_dir, args.source_root
        )
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    for package in packages:
        print(f"Created and structurally verified final package: {package}")
    print("Native clean-extraction smoke is still required for every final package.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
