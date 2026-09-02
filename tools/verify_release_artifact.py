"""Verify staged DLMS native artifacts and optionally smoke-test them in place.

This is intentionally a release-maintainer tool, not a packaging replacement.
It can inspect every staged artifact on any host, while --smoke only runs on the
matching target OS and architecture.  It never imports app.py, so structural
checks cannot initialize a developer's normal DLMS data directory.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import plistlib
import re
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


SERVER_URL = "http://127.0.0.1:9001"
SMOKE_TIMEOUT_SECONDS = 20
SHUTDOWN_TIMEOUT_SECONDS = 12
RUNTIME_DATA_NAMES = {
    ".secret_key",
    "backups",
    "content_packs",
    "data",
    "image_builder_drafts",
    "law",
    "pdf_import_drafts",
    "pdf_question_banks",
    "pdf_terminology_banks",
    "portal.json",
    "quizzes",
    "quizzes.json",
    "quiz_assets",
    "results.db",
    "uploads",
}
TARGETS = {
    "windows-x86_64": {"label": "Windows", "suffix": "windows-x86_64.exe", "system": "Windows", "machine": "x86_64"},
    "linux-x86_64": {"label": "Linux", "suffix": "linux-x86_64", "system": "Linux", "machine": "x86_64"},
    "macos-arm64": {"label": "macOS Apple Silicon", "suffix": "macos-arm64.zip", "system": "Darwin", "machine": "arm64"},
    # This is intentionally optional: use only after a native Intel macOS build
    # and native UAT.  Its presence here does not claim it is a release target.
    "macos-x86_64": {"label": "macOS Intel (optional)", "suffix": "macos-x86_64.zip", "system": "Darwin", "machine": "x86_64"},
}


def _normalized_machine(value: str) -> str:
    value = str(value).lower()
    if value in {"amd64", "x64", "x86_64"}:
        return "x86_64"
    if value in {"arm64", "aarch64"}:
        return "arm64"
    return value


def release_version(source_root: Path) -> str:
    app_source = (source_root / "app.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION = "([^"]+)"$', app_source, re.MULTILINE)
    if match is None:
        raise ValueError("Could not determine APP_VERSION from app.py")
    return match.group(1)


def expected_artifact_name(target: str, version: str) -> str:
    return f"DLMS-{version.replace(' ', '-')}-{TARGETS[target]['suffix']}"


def expected_default_data_dir(target: str, environ: dict[str, str] | None = None) -> str:
    """Return the documented default data location for a target platform."""
    env = os.environ if environ is None else environ
    home = Path.home()
    if target == "windows-x86_64":
        if platform.system() != "Windows":
            return r"%APPDATA%\DLMS"
        return str(Path(env.get("APPDATA") or home) / "DLMS")
    if target.startswith("macos-"):
        if platform.system() != "Darwin":
            return "~/Library/Application Support/DLMS"
        return str(home / "Library" / "Application Support" / "DLMS")
    if platform.system() != "Linux":
        return "$XDG_DATA_HOME/DLMS (or ~/.local/share/DLMS)"
    return str(Path(env.get("XDG_DATA_HOME") or home / ".local" / "share") / "DLMS")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_entries(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line:
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})  \*?([^/\\]+)", raw_line)
        if match is None:
            raise ValueError(f"Invalid SHA256SUMS entry on line {line_number}")
        digest, name = match.groups()
        if name in entries:
            raise ValueError(f"Duplicate SHA256SUMS entry for {name}")
        entries[name] = digest.lower()
    return entries


def verify_checksum(artifact: Path, manifest: Path) -> list[str]:
    try:
        expected = _manifest_entries(manifest).get(artifact.name)
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"Could not read checksum manifest: {exc}"]
    if expected is None:
        return [f"SHA256SUMS.txt does not contain {artifact.name}"]
    actual = sha256_file(artifact)
    if actual != expected:
        return [f"SHA256 mismatch for {artifact.name}: expected {expected}, got {actual}"]
    return []


def _windows_machine(path: Path) -> int | None:
    with path.open("rb") as handle:
        if handle.read(2) != b"MZ":
            return None
        handle.seek(0x3C)
        offset_data = handle.read(4)
        if len(offset_data) != 4:
            return None
        offset = struct.unpack("<I", offset_data)[0]
        handle.seek(offset)
        if handle.read(4) != b"PE\0\0":
            return None
        machine = handle.read(2)
    return struct.unpack("<H", machine)[0] if len(machine) == 2 else None


def _linux_machine(path: Path) -> int | None:
    with path.open("rb") as handle:
        header = handle.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF" or header[4] != 2:
        return None
    byte_order = "<" if header[5] == 1 else ">" if header[5] == 2 else None
    return struct.unpack(f"{byte_order}H", header[18:20])[0] if byte_order else None


def _macos_cpu_types(binary: bytes) -> set[int]:
    if len(binary) < 8:
        return set()
    magic = binary[:4]
    if magic == b"\xcf\xfa\xed\xfe":
        return {struct.unpack("<I", binary[4:8])[0]}
    if magic == b"\xfe\xed\xfa\xcf":
        return {struct.unpack(">I", binary[4:8])[0]}
    if magic not in {b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"} or len(binary) < 8:
        return set()
    count = struct.unpack(">I", binary[4:8])[0]
    entry_size = 24 if magic == b"\xca\xfe\xba\xbf" else 20
    if len(binary) < 8 + count * entry_size:
        return set()
    return {
        struct.unpack(">I", binary[8 + index * entry_size:12 + index * entry_size])[0]
        for index in range(count)
    }


def _contains_runtime_data(member_names: list[str]) -> list[str]:
    offending = []
    for name in member_names:
        parts = [part.casefold() for part in Path(name).parts]
        if RUNTIME_DATA_NAMES.intersection(parts):
            offending.append(name)
    return offending


def _verify_macos_zip(path: Path, target: str) -> list[str]:
    errors: list[str] = []
    expected_cpu = 0x0100000C if target == "macos-arm64" else 0x01000007
    try:
        with zipfile.ZipFile(path) as archive:
            names = [entry.filename.rstrip("/") for entry in archive.infolist() if entry.filename.rstrip("/")]
            prefixes = {name.split("/", 1)[0] for name in names}
            if prefixes != {"DLMS.app"}:
                errors.append("macOS ZIP must contain exactly one top-level DLMS.app bundle")
            required = {"DLMS.app/Contents/Info.plist", "DLMS.app/Contents/MacOS/DLMS"}
            missing = sorted(required.difference(names))
            if missing:
                errors.append("macOS ZIP is missing bundle member(s): " + ", ".join(missing))
            offending = _contains_runtime_data(names)
            if offending:
                errors.append("macOS ZIP includes runtime/user data: " + ", ".join(offending[:5]))
            if "DLMS.app/Contents/Info.plist" in names:
                metadata = plistlib.loads(archive.read("DLMS.app/Contents/Info.plist"))
                if not str(metadata.get("CFBundleGetInfoString") or "").startswith("DLMS "):
                    errors.append("macOS Info.plist does not identify DLMS")
            executable = "DLMS.app/Contents/MacOS/DLMS"
            if executable in names and expected_cpu not in _macos_cpu_types(archive.read(executable)):
                expected_label = "arm64" if target == "macos-arm64" else "x86_64"
                errors.append(f"macOS bundle executable is not a {expected_label} Mach-O binary")
    except (OSError, zipfile.BadZipFile, plistlib.InvalidFileException) as exc:
        errors.append(f"Could not inspect macOS ZIP: {exc}")
    return errors


def verify_artifact(artifact: Path, target: str, version: str) -> list[str]:
    """Return structural/name/architecture errors for one staged artifact."""
    errors: list[str] = []
    expected_name = expected_artifact_name(target, version)
    if not artifact.is_file():
        return [f"Artifact is not a file: {artifact}"]
    if artifact.name != expected_name:
        errors.append(f"Expected artifact name {expected_name}, got {artifact.name}")
    if target == "windows-x86_64":
        if _windows_machine(artifact) != 0x8664:
            errors.append("Windows artifact is not an x86_64 PE executable")
    elif target == "linux-x86_64":
        if _linux_machine(artifact) != 62:
            errors.append("Linux artifact is not an x86_64 ELF executable")
        elif not os.access(artifact, os.X_OK):
            errors.append("Linux artifact is not marked executable")
    else:
        errors.extend(_verify_macos_zip(artifact, target))
    return errors


def _assert_smoke_host(target: str) -> None:
    config = TARGETS[target]
    actual_system = platform.system()
    actual_machine = _normalized_machine(platform.machine())
    if actual_system != config["system"] or actual_machine != config["machine"]:
        raise RuntimeError(
            f"--smoke for {target} must run on native {config['label']} "
            f"({config['system']} {config['machine']}); this host is {actual_system} {actual_machine}."
        )


def _assert_port_available() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", 9001))
        except OSError as exc:
            raise RuntimeError("Port 9001 is in use; stop the existing DLMS server before smoke testing") from exc


def _request(path: str, method: str = "GET") -> tuple[int, bytes]:
    request = urllib.request.Request(f"{SERVER_URL}{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _wait_for_server(process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + SMOKE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"DLMS exited before becoming reachable (exit code {process.returncode})")
        try:
            status, body = _request("/")
            if status == 200 and b"DLMS" in body:
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise RuntimeError("DLMS local server did not become reachable within 20 seconds")


def _assert_smoke_routes() -> None:
    expected = {
        "/": b"DLMS",
        "/static/style.css": b"body",
        "/help/": b"Help",
        "/settings": b"Settings",
        "/library": b"Quiz Library",
    }
    for path, marker in expected.items():
        status, body = _request(path)
        if status != 200 or marker not in body:
            raise RuntimeError(f"Smoke request failed for {path} (HTTP {status})")


def _shutdown_cleanly(process: subprocess.Popen[bytes]) -> None:
    status, _ = _request("/api/shutdown", method="POST")
    if status != 200:
        raise RuntimeError(f"Shutdown DLMS returned HTTP {status}")
    try:
        process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        process.terminate()
        process.wait(timeout=5)
        raise RuntimeError("Shutdown DLMS did not terminate the packaged process cleanly") from exc
    if process.returncode not in {0, -2, 130}:
        raise RuntimeError(f"DLMS exited unexpectedly after shutdown (exit code {process.returncode})")


def _smoke_command(artifact: Path, target: str, work_root: Path) -> list[str]:
    if target == "windows-x86_64" or target == "linux-x86_64":
        return [str(artifact), "--no-browser"]
    extraction_root = work_root / "macos-artifact"
    with zipfile.ZipFile(artifact) as archive:
        archive.extractall(extraction_root)
    executable = extraction_root / "DLMS.app" / "Contents" / "MacOS" / "DLMS"
    executable.chmod(executable.stat().st_mode | 0o111)
    return [str(executable), "--no-browser"]


def smoke_test(artifact: Path, target: str) -> None:
    """Launch, probe, cleanly shut down, and restart a native packaged artifact."""
    _assert_smoke_host(target)
    _assert_port_available()
    with tempfile.TemporaryDirectory(prefix="dlms-native-artifact-smoke-") as temporary:
        work_root = Path(temporary)
        data_root = work_root / "data-root"
        command = _smoke_command(artifact, target, work_root)
        environment = os.environ.copy()
        environment["QUIZAPP_DATA_DIR"] = str(data_root)
        environment["DLMS_NO_BROWSER"] = "1"
        for run_number in (1, 2):
            with (work_root / f"run-{run_number}.log").open("wb") as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=environment)
                try:
                    _wait_for_server(process)
                    _assert_smoke_routes()
                    _shutdown_cleanly(process)
                except Exception:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=5)
                    raise
        if not (data_root / ".dlms-data-root").is_file():
            raise RuntimeError("Packaged DLMS did not initialize the isolated smoke-test data root")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a staged DLMS native release artifact.")
    parser.add_argument("target", choices=sorted(TARGETS), help="artifact target to verify")
    parser.add_argument("artifact", nargs="?", type=Path, help="staged final artifact")
    parser.add_argument("--checksums", type=Path, help="SHA256SUMS.txt to verify against")
    parser.add_argument("--smoke", action="store_true", help="run native start/HTTP/shutdown/restart smoke test")
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root used only to read APP_VERSION")
    parser.add_argument("--print-expected-data-dir", action="store_true", help="print the target platform's normal user data location")
    args = parser.parse_args(argv)

    if args.print_expected_data_dir:
        print(expected_default_data_dir(args.target))
        return 0
    if args.artifact is None:
        parser.error("artifact is required unless --print-expected-data-dir is used")
    try:
        version = release_version(args.source_root.resolve())
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    errors = verify_artifact(args.artifact.resolve(), args.target, version)
    if args.checksums:
        errors.extend(verify_checksum(args.artifact.resolve(), args.checksums.resolve()))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Verified {args.artifact.name} for {TARGETS[args.target]['label']}.")
    if args.smoke:
        try:
            smoke_test(args.artifact.resolve(), args.target)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            print(f"ERROR: Native smoke test failed: {exc}", file=sys.stderr)
            return 1
        print("Native launch, route, clean shutdown, and restart smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
