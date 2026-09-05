"""Verify staged DLMS native artifacts and optionally smoke-test them in place.

This is intentionally a release-maintainer tool, not a packaging replacement.
It can inspect every staged artifact on any host, while --smoke only runs on the
matching target OS and architecture.  It never imports app.py, so structural
checks cannot initialize a developer's normal DLMS data directory.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import hashlib
import os
import platform
import plistlib
import re
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


SERVER_URL = "http://127.0.0.1:9001"
SMOKE_TIMEOUT_SECONDS = 20
SHUTDOWN_TIMEOUT_SECONDS = 12
MACOS_DITTO = Path("/usr/bin/ditto")
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
    "windows-x86_64": {
        "label": "Windows",
        "suffixes": ("windows11-x86_64.exe",),
        "system": "Windows",
        "machine": "x86_64",
    },
    "linux-x86_64": {
        "label": "Linux",
        "suffixes": (
            "fedora44-x86_64",
            "ubuntu24.04-x86_64",
            "ubuntu26.04-x86_64",
            "omarchy-quattro-x86_64",
        ),
        "system": "Linux",
        "machine": "x86_64",
    },
    "macos-arm64": {
        "label": "macOS Apple Silicon",
        "suffixes": ("macos-arm64.zip",),
        "system": "Darwin",
        "machine": "arm64",
    },
    # This is intentionally optional: use only after a native Intel macOS build
    # and native UAT.  Its presence here does not claim it is a release target.
    "macos-x86_64": {
        "label": "macOS Intel (optional)",
        "suffixes": ("macos-x86_64.zip",),
        "system": "Darwin",
        "machine": "x86_64",
    },
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


def expected_artifact_names(target: str, version: str) -> tuple[str, ...]:
    prefix = f"DLMS-{version.replace(' ', '-')}-"
    return tuple(prefix + suffix for suffix in TARGETS[target]["suffixes"])


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


def _host_posix_executable(
    path: Path,
    *,
    host_system: str | None = None,
) -> bool | None:
    """Return the POSIX execute-bit state, or None on a non-POSIX host."""
    system = platform.system() if host_system is None else host_system
    if system not in {"Linux", "Darwin"}:
        return None
    execute_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    return bool(path.stat().st_mode & execute_bits)


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


def _macos_bundle_versions(release_version: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?: RC(\d+))?", release_version)
    if match is None:
        return None
    short_version, candidate = match.groups()
    build_version = short_version if candidate is None else f"{short_version}fc{candidate}"
    return short_version, build_version


def _verify_macos_zip(path: Path, target: str, version: str) -> list[str]:
    errors: list[str] = []
    expected_cpu = 0x0100000C if target == "macos-arm64" else 0x01000007
    bundle_versions = _macos_bundle_versions(version)
    try:
        with zipfile.ZipFile(path) as archive:
            names: list[str] = []
            seen: dict[str, str] = {}
            for entry in archive.infolist():
                raw_name = entry.filename
                if (
                    not raw_name
                    or "\\" in raw_name
                    or raw_name.startswith("/")
                ):
                    errors.append(f"unsafe macOS ZIP member path: {raw_name!r}")
                    continue
                name = raw_name.rstrip("/")
                parts = PurePosixPath(name).parts
                if not parts or any(part in {"", ".", ".."} for part in parts):
                    errors.append(f"unsafe macOS ZIP member path: {raw_name!r}")
                    continue
                folded = name.casefold()
                if folded in seen:
                    errors.append(
                        "case-colliding or duplicate macOS ZIP members: "
                        f"{seen[folded]} and {name}"
                    )
                else:
                    seen[folded] = name
                if name == "__MACOSX" or name.startswith("__MACOSX/"):
                    if (
                        name not in {"__MACOSX", "__MACOSX/DLMS.app"}
                        and name != "__MACOSX/._DLMS.app"
                        and not name.startswith("__MACOSX/DLMS.app/")
                    ):
                        errors.append(f"unexpected macOS metadata path: {name}")
                    continue
                names.append(name)
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
            if not any(
                name.startswith("DLMS.app/Contents/Resources/") for name in names
            ):
                errors.append("macOS ZIP is missing bundled Resources content")
            if "DLMS.app/Contents/Info.plist" in names:
                metadata = plistlib.loads(archive.read("DLMS.app/Contents/Info.plist"))
                if metadata.get("CFBundleGetInfoString") != f"DLMS {version}":
                    errors.append("macOS Info.plist release version does not match APP_VERSION")
                if bundle_versions is None:
                    errors.append("APP_VERSION is not compatible with macOS bundle metadata")
                else:
                    short_version, build_version = bundle_versions
                    if metadata.get("CFBundleShortVersionString") != short_version:
                        errors.append("macOS CFBundleShortVersionString does not match APP_VERSION")
                    if metadata.get("CFBundleVersion") != build_version:
                        errors.append("macOS CFBundleVersion does not match APP_VERSION")
                if metadata.get("CFBundleExecutable") != "DLMS":
                    errors.append("macOS CFBundleExecutable is not DLMS")
                if metadata.get("CFBundleIdentifier") != "io.github.drakahari.DLMS":
                    errors.append(
                        "macOS CFBundleIdentifier is not io.github.drakahari.DLMS"
                    )
            executable = "DLMS.app/Contents/MacOS/DLMS"
            if executable in names:
                info = archive.getinfo(executable)
                mode = info.external_attr >> 16
                if info.create_system == 3 and not mode & (
                    stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                ):
                    errors.append(
                        "macOS bundle executable does not retain an execute permission bit"
                    )
                if expected_cpu not in _macos_cpu_types(archive.read(executable)):
                    expected_label = "arm64" if target == "macos-arm64" else "x86_64"
                    errors.append(f"macOS bundle executable is not a {expected_label} Mach-O binary")
    except (OSError, zipfile.BadZipFile, plistlib.InvalidFileException) as exc:
        errors.append(f"Could not inspect macOS ZIP: {exc}")
    return errors


def verify_artifact(artifact: Path, target: str, version: str) -> list[str]:
    """Return structural/name/architecture errors for one staged artifact."""
    errors: list[str] = []
    expected_names = expected_artifact_names(target, version)
    if not artifact.is_file():
        return [f"Artifact is not a file: {artifact}"]
    if artifact.name not in expected_names:
        expected = ", ".join(expected_names)
        errors.append(f"Expected artifact name to be one of: {expected}; got {artifact.name}")
    if target == "windows-x86_64":
        if _windows_machine(artifact) != 0x8664:
            errors.append("Windows artifact is not an x86_64 PE executable")
    elif target == "linux-x86_64":
        if _linux_machine(artifact) != 62:
            errors.append("Linux artifact is not an x86_64 ELF executable")
        elif _host_posix_executable(artifact) is False:
            errors.append("Linux artifact is not marked executable")
    else:
        errors.extend(_verify_macos_zip(artifact, target, version))
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


class SmokeHttpClient:
    """Small same-origin browser-session analogue for the native smoke test."""

    def __init__(self) -> None:
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def csrf_token(self) -> str:
        for cookie in self.cookies:
            if cookie.name == "dlms_csrf_token":
                return cookie.value
        raise RuntimeError("DLMS did not provide a CSRF token cookie during the smoke-test session")


def _request(
    path: str,
    method: str = "GET",
    *,
    client: SmokeHttpClient | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    request = urllib.request.Request(f"{SERVER_URL}{path}", headers=headers or {}, method=method)
    try:
        opener = client.opener if client is not None else None
        response_context = (
            opener.open(request, timeout=1.5)
            if opener is not None
            else urllib.request.urlopen(request, timeout=1.5)
        )
        with response_context as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _wait_for_server(process: subprocess.Popen[bytes], client: SmokeHttpClient) -> None:
    deadline = time.monotonic() + SMOKE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"DLMS exited before becoming reachable (exit code {process.returncode})")
        try:
            status, body = _request("/", client=client)
            if status == 200 and b"DLMS" in body:
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise RuntimeError("DLMS local server did not become reachable within 20 seconds")


def _assert_smoke_routes(client: SmokeHttpClient) -> None:
    expected = {
        "/": b"DLMS",
        "/static/style.css": b"body",
        "/help/": b"Help",
        "/settings": b"Settings",
        "/library": b"Quiz Library",
    }
    for path, marker in expected.items():
        status, body = _request(path, client=client)
        if status != 200 or marker not in body:
            raise RuntimeError(f"Smoke request failed for {path} (HTTP {status})")


def _clean_shutdown_returncodes(target: str) -> set[int]:
    """Return only the normal completion statuses for an acknowledged shutdown."""
    if target == "windows-x86_64":
        # DLMS deliberately raises SIGINT after responding to /api/shutdown.
        # The Windows PyInstaller process reports that controlled interruption
        # as status 2, rather than a POSIX signal-derived return code.
        return {0, 2}
    return {0, -2, 130}


def _shutdown_cleanly(process: subprocess.Popen[bytes], client: SmokeHttpClient, target: str) -> None:
    # Match the in-app fetch contract: retain the HTML session cookies, send the
    # session-bound CSRF token, and declare the local request origin explicitly.
    status, _ = _request(
        "/api/shutdown",
        method="POST",
        client=client,
        headers={
            "X-CSRFToken": client.csrf_token(),
            "Origin": SERVER_URL,
            "Referer": f"{SERVER_URL}/",
            "Sec-Fetch-Site": "same-origin",
        },
    )
    if status != 200:
        raise RuntimeError(f"Shutdown DLMS returned HTTP {status}")
    try:
        process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        process.terminate()
        process.wait(timeout=5)
        raise RuntimeError("Shutdown DLMS did not terminate the packaged process cleanly") from exc
    if process.returncode not in _clean_shutdown_returncodes(target):
        raise RuntimeError(f"DLMS exited unexpectedly after shutdown (exit code {process.returncode})")


def _extract_macos_bundle_for_smoke(artifact: Path, extraction_root: Path) -> Path:
    """Extract the app with macOS tooling so bundle symlinks remain intact."""
    ditto = MACOS_DITTO
    if not ditto.is_file():
        raise RuntimeError("macOS ditto is required to extract a native DLMS.app smoke artifact")
    extraction_root.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(ditto), "-x", "-k", str(artifact), str(extraction_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail[-1200:]}" if detail else ""
        raise RuntimeError(f"macOS ditto extraction failed (exit code {result.returncode}){suffix}")
    executable = extraction_root / "DLMS.app" / "Contents" / "MacOS" / "DLMS"
    if not executable.is_file() or _host_posix_executable(executable) is False:
        raise RuntimeError("macOS ditto extraction did not produce an executable DLMS.app bundle")
    return executable


def _smoke_command(artifact: Path, target: str, work_root: Path) -> list[str]:
    if target == "windows-x86_64" or target == "linux-x86_64":
        return [str(artifact), "--no-browser"]
    extraction_root = work_root / "macos-artifact"
    executable = _extract_macos_bundle_for_smoke(artifact, extraction_root)
    return [str(executable), "--no-browser"]


def _launch_log_tail(path: Path, limit: int = 8000) -> str:
    try:
        contents = path.read_bytes()[-limit:].decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    return contents


def _smoke_environment(data_root: Path, target: str, source: dict[str, str] | None = None) -> dict[str, str]:
    """Return an isolated environment suitable for a packaged DLMS launch."""
    environment = dict(os.environ if source is None else source)
    environment["QUIZAPP_DATA_DIR"] = str(data_root)
    environment["DLMS_NO_BROWSER"] = "1"
    if target.startswith("macos-"):
        # Finder does not inherit the calling shell's Python launcher settings.
        # Let the PyInstaller runtime select only the Python embedded in DLMS.app.
        for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "__PYVENV_LAUNCHER__", "VIRTUAL_ENV"):
            environment.pop(name, None)
    return environment


def _run_smoke_command(command: list[str], target: str, work_root: Path) -> None:
    """Exercise one already-resolved native command in an isolated data root."""
    data_root = work_root / "data-root"
    environment = _smoke_environment(data_root, target)
    for run_number in (1, 2):
        with (work_root / f"run-{run_number}.log").open("wb") as log:
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=environment,
                cwd=str(work_root),
            )
            client = SmokeHttpClient()
            try:
                _wait_for_server(process, client)
                _assert_smoke_routes(client)
                _shutdown_cleanly(process, client, target)
            except Exception as exc:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                log.flush()
                diagnostics = _launch_log_tail(Path(log.name))
                if diagnostics:
                    raise RuntimeError(
                        f"{exc}\nPackaged launch diagnostics (last 8000 bytes):\n{diagnostics}"
                    ) from exc
                raise
    if not (data_root / ".dlms-data-root").is_file():
        raise RuntimeError("Packaged DLMS did not initialize the isolated smoke-test data root")


def smoke_test_executable(executable: Path, target: str) -> None:
    """Smoke-test an executable already extracted from the final distributable."""
    _assert_smoke_host(target)
    _assert_port_available()
    if not executable.is_file():
        raise RuntimeError(f"extracted DLMS executable does not exist: {executable}")
    with tempfile.TemporaryDirectory(prefix="dlms-final-package-smoke-") as temporary:
        _run_smoke_command(
            [str(executable), "--no-browser"], target, Path(temporary)
        )


def smoke_test(artifact: Path, target: str) -> None:
    """Launch, probe, cleanly shut down, and restart a staged native artifact."""
    _assert_smoke_host(target)
    _assert_port_available()
    with tempfile.TemporaryDirectory(prefix="dlms-native-artifact-smoke-") as temporary:
        work_root = Path(temporary)
        command = _smoke_command(artifact, target, work_root)
        _run_smoke_command(command, target, work_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a staged DLMS native release artifact.")
    parser.add_argument("target", choices=sorted(TARGETS), help="artifact target to verify")
    parser.add_argument("artifact", nargs="?", type=Path, help="staged native input")
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
