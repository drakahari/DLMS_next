"""Experimental additive Linux desktop package; native tar.gz targets stay canonical.

Compose the native clean-build/OCR/smoke gates with local, hash-pinned AppImage
tools. No network download or desktop installation occurs in this workflow.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from build_native_release import build_frozen, linux_preflight, run_stage, source_preflight
from native_icons import desktop_icon
from package_release import LINUX_PLATFORMS
from verify_release_artifact import (
    _assert_port_available, _assert_smoke_host, _run_smoke_command,
    release_version, sha256_file,
)
from pyinstaller_ocr import validate_tesseract_bundle

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = """[Desktop Entry]
Type=Application
Name=DLMS
Comment=Local-first study and quiz workspace
Exec=DLMS
Icon=dlms
Terminal=false
Categories=Education;
StartupNotify=false
"""
APPRUN = '''#!/bin/sh
set -eu
appdir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$appdir/usr/bin/DLMS" "$@"
'''


def checked_tool(path: Path, expected: str) -> Path:
    path = path.resolve()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("Tool SHA-256 must contain exactly 64 hexadecimal characters")
    if sha256_file(path) != expected.lower():
        raise ValueError(f"Tool checksum mismatch: {path.name}")
    return path


def stage_appdir(binary: Path, destination: Path, root: Path = ROOT) -> None:
    destination.mkdir()  # Never reuse an old AppDir.
    (destination / "usr/bin").mkdir(parents=True)
    shutil.copy2(binary, destination / "usr/bin/DLMS")
    (destination / "usr/bin/DLMS").chmod(0o755)
    (destination / "AppRun").write_text(APPRUN, encoding="utf-8")
    (destination / "AppRun").chmod(0o755)
    (destination / "dlms.desktop").write_text(DESKTOP, encoding="utf-8")
    desktop_icon(root / "static/favicon.ico", destination / "dlms.png")
    (destination / ".DirIcon").symlink_to("dlms.png")
    applications = destination / "usr/share/applications"
    applications.mkdir(parents=True)
    (applications / "dlms.desktop").symlink_to("../../../dlms.desktop")
    icons = destination / "usr/share/icons/hicolor/256x256/apps"
    icons.mkdir(parents=True)
    (icons / "dlms.png").symlink_to("../../../../../../dlms.png")
    for name in ("README.txt", "sample_quiz.txt"):
        shutil.copy2(root / "release_assets" / name, destination / name)


def verify_appdir(directory: Path, binary_hash: str) -> None:
    from PIL import Image
    if (directory / "AppRun").read_text() != APPRUN or not os.access(directory / "AppRun", os.X_OK):
        raise ValueError("Invalid AppRun entry point")
    # appimagetool may append X-AppImage-Version metadata.
    if not (directory / "dlms.desktop").read_text().startswith(DESKTOP):
        raise ValueError("Invalid desktop metadata")
    if len(list(directory.glob("*.desktop"))) != 1:
        raise ValueError("AppDir must have one desktop entry")
    binary = directory / "usr/bin/DLMS"
    if not os.access(binary, os.X_OK) or sha256_file(binary) != binary_hash:
        raise ValueError("Packaged application does not match the fresh native build")
    for name in (".DirIcon", "usr/share/icons/hicolor/256x256/apps/dlms.png"):
        if (directory / name).resolve() != (directory / "dlms.png").resolve():
            raise ValueError("Broken application icon link")
    if (directory / "usr/share/applications/dlms.desktop").resolve() != (directory / "dlms.desktop").resolve():
        raise ValueError("Broken desktop entry link")
    with Image.open(directory / "dlms.png") as image:
        if image.format != "PNG" or image.size != (256, 256):
            raise ValueError("Invalid desktop icon")
    for name in ("README.txt", "sample_quiz.txt"):
        if not (directory / name).is_file():
            raise ValueError(f"Missing support document: {name}")


def smoke_appimage(image: Path, version: str, mode: str) -> None:
    _assert_smoke_host("linux-x86_64")
    _assert_port_available()
    command = [str(image.resolve())]
    if mode == "extract":
        command.append("--appimage-extract-and-run")
    command.append("--no-browser")
    with tempfile.TemporaryDirectory(prefix="dlms-appimage-smoke-") as temporary:
        # Existing gate checks routes, running APP_VERSION, CSRF shutdown,
        # restart, and ownership of a data root outside the mounted image.
        _run_smoke_command(command, "linux-x86_64", Path(temporary), version)


def build(args, root: Path = ROOT):
    _assert_smoke_host("linux-x86_64")
    distribution = linux_preflight(args.target)
    _assert_port_available()
    version = release_version(root)
    if version != args.expected_version:
        raise ValueError("Expected version does not match APP_VERSION")
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if not args.candidate:
        source_preflight(root, args.expected_commit, version)
    tool = checked_tool(args.appimagetool, args.appimagetool_sha256)
    runtime = checked_tool(args.runtime_file, args.runtime_sha256)
    bundle = args.ocr_bundle.resolve()
    validate_tesseract_bundle(bundle)
    output = args.output_dir.resolve()
    if output.exists():
        raise ValueError("Output directory must not already exist")
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, DLMS_TESSERACT_BUNDLE_ROOT=str(bundle), ARCH="x86_64", VERSION=version)
    run_stage("dependency preflight", [sys.executable, "-m", "pip", "check"], root=root, environment=environment)
    with tempfile.TemporaryDirectory(prefix=".dlms-appimage-build-", dir=output.parent) as temporary:
        work = Path(temporary)
        environment["PYINSTALLER_CONFIG_DIR"] = str(work / "cache")
        probe = build_frozen(root / "DLMS-OCR-Probe.spec", work / "probe", root=root, environment=environment)
        run_stage("frozen OCR probe", [probe / "DLMS-OCR-Probe"], root=root, environment=environment)
        native = build_frozen(root / "DLMS.spec", work / "native", root=root, environment=environment)
        binary_hash = sha256_file(native / "DLMS")
        appdir = work / "DLMS.AppDir"
        stage_appdir(native / "DLMS", appdir, root)
        verify_appdir(appdir, binary_hash)
        run_stage("desktop metadata", ["desktop-file-validate", appdir / "dlms.desktop"], root=root, environment=environment)
        accepted = work / "output"
        accepted.mkdir()
        image = accepted / f"DLMS-{version}-{args.target}.AppImage"
        # Execute the tool without FUSE and pin its runtime; no implicit download.
        run_stage("AppImage assembly", [tool, "--appimage-extract-and-run", "--no-appstream",
                  "--runtime-file", runtime, appdir, image], root=root, environment=environment)
        extraction = work / "verify"
        extraction.mkdir()
        subprocess.run([str(image), "--appimage-extract"], cwd=extraction, check=True,
                       stdout=subprocess.DEVNULL, timeout=120)
        verify_appdir(extraction / "squashfs-root", binary_hash)
        smoke_appimage(image, version, args.smoke_mode)
        if not args.candidate:
            source_preflight(root, args.expected_commit, version)
        record = {"status": "experimental-candidate", "version": version, "target": args.target,
                  "source_commit": commit, "frozen_source": not args.candidate,
                  "host": distribution, "sha256": sha256_file(image), "package": image.name,
                  "native_binary_sha256": binary_hash, "appimagetool_sha256": args.appimagetool_sha256,
                  "runtime_sha256": args.runtime_sha256, "smoke_mode": args.smoke_mode,
                  "layout_verified": True, "runtime_version_shutdown_restart": "PASS",
                  "frozen_ocr_probe": "PASS", "cross_distribution_acceptance": "PENDING"}
        (accepted / "SHA256SUMS.txt").write_text(f"{record['sha256']}  {image.name}\n")
        (accepted / "evaluation.json").write_text(json.dumps(record, indent=2) + "\n")
        if output.exists():
            raise ValueError("Output appeared during build; refusing to overwrite it")
        accepted.rename(output)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=LINUX_PLATFORMS)
    parser.add_argument("--expected-version", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--expected-commit", help="full frozen source SHA")
    source.add_argument("--candidate", action="store_true", help="explicitly evaluate uncommitted source; never release acceptance")
    parser.add_argument("--appimagetool", type=Path, required=True)
    parser.add_argument("--appimagetool-sha256", required=True)
    parser.add_argument("--runtime-file", type=Path, required=True)
    parser.add_argument("--runtime-sha256", required=True)
    parser.add_argument("--ocr-bundle", type=Path, default=ROOT / ".ocr-bundle")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--smoke-mode", choices=("fuse", "extract"), default="fuse")
    args = parser.parse_args(argv)
    try:
        record = build(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"DLMS APPIMAGE EVALUATION FAILED: {exc}", file=sys.stderr)
        return 1
    print("DLMS EXPERIMENTAL APPIMAGE BUILT\n" + json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
