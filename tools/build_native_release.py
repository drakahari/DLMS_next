"""Target-native release orchestration using the existing DLMS release gates."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

from package_release import LINUX_PLATFORMS, RELEASE_TARGETS, _single_target_contract, package_single_target
from verify_release_artifact import (
    _assert_port_available, _assert_smoke_host, release_version, sha256_file,
    smoke_test, verify_artifact,
)


ROOT = Path(__file__).resolve().parents[1]


class ReleaseError(RuntimeError):
    pass


def linux_preflight(target):
    """Reject mislabeled Fedora/Ubuntu builds; Omarchy is Arch-based.

    /etc/os-release cannot prove an Omarchy installation/edition on Arch.
    Selecting that target is also the maintainer's explicit edition assertion.
    """
    if target not in LINUX_PLATFORMS:
        return {}
    distribution = platform.freedesktop_os_release()
    identifier = distribution.get("ID", "").lower()
    version = distribution.get("VERSION_ID", "")
    expected = {"fedora44-x86_64": ("fedora", "44"),
                "ubuntu24.04-x86_64": ("ubuntu", "24.04"),
                "ubuntu26.04-x86_64": ("ubuntu", "26.04")}
    if target in expected and (identifier, version) != expected[target]:
        raise ReleaseError(f"{target} requires {expected[target]}; host reports {(identifier, version)}")
    if target == "omarchy-quattro-x86_64" and identifier not in {"arch", "omarchy"}:
        raise ReleaseError("Omarchy builds require the native Arch/Omarchy host")
    return {key: distribution.get(key, "") for key in ("ID", "VERSION_ID", "PRETTY_NAME")}


def run_stage(name, command, *, root, environment):
    print(f"[{name}]", flush=True)
    try:
        subprocess.run([str(value) for value in command], cwd=root,
                       env=environment, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseError(f"{name} failed: {exc}") from exc


def source_preflight(root, expected_commit, expected_version):
    """No dirty-source override: acceptance always identifies frozen source."""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_commit):
        raise ReleaseError("--expected-commit must be the full 40-character commit SHA")
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()
    commit = git("rev-parse", "HEAD")
    if commit != expected_commit.lower():
        raise ReleaseError(f"Source commit mismatch: expected {expected_commit}, found {commit}")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ReleaseError("Release source must be clean, including untracked files")
    version = release_version(root)
    if version != expected_version:
        raise ReleaseError(f"Source version mismatch: expected {expected_version}, found {version}")
    return commit, version


def build_frozen(spec, destination, *, root, environment):
    """Fresh per-stage work/dist paths, never repository build/ or dist/.

    Refusing an existing directory is intentional: no stale output may be
    accepted even if PyInstaller exits successfully without replacing a file.
    """
    destination.mkdir()  # exist_ok=False; parent is the task-owned workspace
    work = destination / "build"
    dist = destination / "dist"
    run_stage(spec.stem, [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
                         "--workpath", work, "--distpath", dist, spec],
              root=root, environment=environment)
    return dist


def acceptance_text(record):
    return ("DLMS NATIVE RELEASE ACCEPTED\n"
            f"Target: {record['target']}\nVersion: {record['version']}\n"
            f"Commit: {record['commit']}\nPackage: {record['package']}\n"
            f"SHA-256: {record['sha256']}")


def orchestrate(args, *, root=ROOT):
    if args.target not in RELEASE_TARGETS:
        raise ReleaseError(f"Unsupported release target: {args.target}")
    commit, version = source_preflight(root, args.expected_commit, args.expected_version)
    native_target, artifact_name, package_name = _single_target_contract(args.target, version)
    _assert_smoke_host(native_target)
    distribution = linux_preflight(args.target)
    _assert_port_available()
    output = (args.output_dir or root / "build/native-release" / version / args.target / commit).resolve()
    if output.exists():
        raise ReleaseError(f"Refusing to replace existing release output: {output}")
    bundle = args.ocr_bundle.resolve()
    environment = os.environ.copy()
    environment["DLMS_TESSERACT_BUNDLE_ROOT"] = str(bundle)
    run_stage("dependency preflight", [sys.executable, "-B", root / "tools/check_release_dependencies.py"],
              root=root, environment=environment)
    bundle_command = [sys.executable, root / "tools/prepare_ocr_bundle.py", "--output", bundle]
    if args.prepare_ocr:
        for option in ("tesseract_executable", "tessdata_dir", "tesseract_license",
                       "tessdata_license", "leptonica_license", "license_cache"):
            if value := getattr(args, option):
                bundle_command += ["--" + option.replace("_", "-"), value]
        if args.download_missing_licenses:
            bundle_command.append("--download-missing-licenses")
    else:
        bundle_command.append("--validate-only")
    run_stage("OCR bundle preparation" if args.prepare_ocr else "OCR bundle validation",
              bundle_command, root=root, environment=environment)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Same filesystem as final output permits atomic promotion of the entire
    # accepted package/checksum/report directory. Failure publishes nothing.
    with tempfile.TemporaryDirectory(prefix=".dlms-native-release-", dir=output.parent) as temporary:
        work = Path(temporary)
        environment["PYINSTALLER_CONFIG_DIR"] = str(work / "pyinstaller-cache")
        probe_dist = build_frozen(root / "DLMS-OCR-Probe.spec", work / "probe",
                                  root=root, environment=environment)
        suffix = ".exe" if native_target == "windows-x86_64" else ""
        run_stage("frozen OCR probe", [probe_dist / ("DLMS-OCR-Probe" + suffix)],
                  root=root, environment=environment)
        app_dist = build_frozen(root / "DLMS.spec", work / "application",
                                root=root, environment=environment)
        staged = work / "staged"
        staged.mkdir()
        artifact = staged / artifact_name
        if native_target == "macos-arm64":
            run_stage("native macOS archive", ["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc",
                      "--keepParent", app_dist / "DLMS.app", artifact], root=root, environment=environment)
        else:
            shutil.copy2(app_dist / ("DLMS" + suffix), artifact)
        errors = verify_artifact(artifact, native_target, version)
        if errors:
            raise ReleaseError("Native artifact verification failed: " + "; ".join(errors))
        print("[native artifact smoke and runtime version]", flush=True)
        smoke_test(artifact, native_target, version)
        print("[final package, clean extraction and native smoke]", flush=True)
        accepted = work / "accepted"
        package = package_single_target(args.target, artifact, accepted, root, smoke=True)
        # Detect tracked or untracked source changes during the build as well.
        source_preflight(root, commit, version)
        digest = sha256_file(package)
        record = {"status": "accepted", "target": args.target, "version": version,
                  "commit": commit, "package": str(output / package_name), "sha256": digest,
                  "host": {"system": platform.system(), "machine": platform.machine(),
                           "distribution": distribution}}
        (accepted / "SHA256SUMS.txt").write_text(f"{digest}  {package_name}\n", encoding="utf-8")
        (accepted / "acceptance.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        # Refuse an output created by another invocation while this one built.
        if output.exists():
            raise ReleaseError(f"Release output appeared during build: {output}")
        accepted.rename(output)
    return record


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--target", required=True, choices=RELEASE_TARGETS)
    result.add_argument("--expected-commit", required=True)
    result.add_argument("--expected-version", required=True)
    result.add_argument("--output-dir", type=Path, help="new acceptance directory; never overwritten")
    result.add_argument("--ocr-bundle", type=Path, default=ROOT / ".ocr-bundle")
    result.add_argument("--prepare-ocr", action="store_true", help="prepare a new native bundle instead of validating one")
    for option in ("tesseract-executable", "tessdata-dir", "tesseract-license",
                   "tessdata-license", "leptonica-license", "license-cache"):
        result.add_argument("--" + option)
    result.add_argument("--download-missing-licenses", action="store_true")
    return result


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if not args.prepare_ocr and (args.download_missing_licenses or any(
            getattr(args, option) for option in ("tesseract_executable", "tessdata_dir",
                "tesseract_license", "tessdata_license", "leptonica_license", "license_cache"))):
        argument_parser.error("OCR preparation options require --prepare-ocr")
    try:
        record = orchestrate(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"DLMS NATIVE RELEASE FAILED\nTarget: {args.target}\n"
              f"Version: {args.expected_version}\nCommit: {args.expected_commit}\n{exc}", file=sys.stderr)
        return 1
    print(acceptance_text(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
