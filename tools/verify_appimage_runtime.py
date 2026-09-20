"""Fedora/native-host evaluation of a trusted locally built DLMS AppImage.

Use synthetic OCR/PDF input and a temporary data root. Browser dispatch is
captured by a stub, never by opening the maintainer's real browser session.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

from PIL import Image
from build_appimage import smoke_appimage
from verify_release_artifact import (
    SERVER_URL, SmokeHttpClient, _assert_port_available, _assert_smoke_host,
    _assert_smoke_routes, _request, _shutdown_cleanly, _smoke_environment, _wait_for_server,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[1]


def verify_browser_environment(record, expected_library_path):
    """Fail even on hosts where leaked libraries happen to be ABI-compatible."""
    lines = record.splitlines()
    if lines != [SERVER_URL, expected_library_path]:
        raise RuntimeError("Browser child did not receive the URL and original host library path")


def post(client, path, fields, file=None):
    headers = {"X-CSRFToken": client.csrf_token(), "Origin": SERVER_URL}
    if file is None:
        body = urllib.parse.urlencode(fields).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    else:
        field, filename, mime, payload = file
        boundary = "dlms-appimage-synthetic-probe"
        parts = []
        for key, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode() + payload + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    with client.opener.open(urllib.request.Request(SERVER_URL + path, data=body, headers=headers), timeout=60) as response:
        return response.geturl(), response.read()


def ocr_workflows(client):
    fixture = (ROOT / "tests/fixtures/ocr/dlms-question.png").read_bytes()
    fields = {"rights_ok": "1", "quiz_title": "AppImage synthetic OCR", "exam_minutes": "30"}
    url, _ = post(client, "/pdf-import/screenshots", fields,
                  ("screenshots", "synthetic.png", "image/png", fixture))
    draft = url.rsplit("/", 1)[1]
    _, data = post(client, f"/pdf-import/screenshots/process/{draft}/next", {})
    screenshot = json.loads(data)
    if screenshot.get("failed") != 0 or not screenshot.get("has_results"):
        raise RuntimeError(f"AppImage screenshot OCR did not recover results: {screenshot}")
    with Image.open(io.BytesIO(fixture)) as image:
        pdf = io.BytesIO()
        # Match the application's 300-DPI renderer so this packaging fixture
        # does not add unnecessary scaling blur before OCR.
        image.convert("RGB").save(pdf, format="PDF", resolution=300, quality=100)
    url, _ = post(client, "/pdf-import/analyze", fields,
                  ("pdf_file", "synthetic-scan.pdf", "application/pdf", pdf.getvalue()))
    # Follow the actual selective OCR offer rather than injecting a draft.
    if "/ocr/" not in url:
        raise RuntimeError(f"Scanned PDF did not offer selective OCR: {url}")
    draft = url.rstrip("/").rsplit("/", 1)[1]
    # Routes use /pdf-import/ocr/<id> for the offer.
    post(client, f"/pdf-import/ocr/{draft}/start", {"ocr_pages": "1"})
    _, data = post(client, f"/pdf-import/ocr/{draft}/process/next", {})
    scanned = json.loads(data)
    if scanned.get("failed") != 0 or not scanned.get("has_results"):
        raise RuntimeError(f"AppImage PDFium/OCR did not recover results: {scanned}")
    for label, result in (("screenshot", screenshot), ("scanned PDF", scanned)):
        with client.opener.open(SERVER_URL + result["review_url"], timeout=10) as response:
            page = response.read()
        if b"https" not in page.lower() or b"protocol" not in page.lower():
            raise RuntimeError(f"{label} OCR review missing expected text: "
                               f"HTTPS={b'https' in page.lower()}, protocol={b'protocol' in page.lower()}")
    return {"screenshot_ocr": "PASS", "pdfium_scanned_pdf_ocr": "PASS"}


def evaluate(image: Path, version: str, *, lan=False):
    image = image.resolve()
    digest = sha256_file(image)
    _assert_smoke_host("linux-x86_64")
    _assert_port_available()
    smoke_appimage(image, version, "extract")
    result = {"image": str(image), "sha256": digest, "extract_shutdown_restart": "PASS"}
    with tempfile.TemporaryDirectory(prefix="dlms-appimage-runtime-") as temporary:
        work = Path(temporary)
        data_root = work / "data-root"
        environment = _smoke_environment(data_root, "linux-x86_64")
        environment.pop("DLMS_NO_BROWSER", None)
        browser = work / "browser-stub"
        browser.write_text('#!/bin/sh\nprintf "%s\\n" "$1" "${LD_LIBRARY_PATH-}" > "$DLMS_BROWSER_PROBE"\n')
        browser.chmod(0o755)
        opened = work / "browser-url"
        environment.update(BROWSER=str(browser), DLMS_BROWSER_PROBE=str(opened))
        # A harmless empty host directory proves restoration, not just removal.
        host_libraries = work / "host-libraries"
        host_libraries.mkdir()
        environment["LD_LIBRARY_PATH"] = str(host_libraries)
        # A bogus override must not replace the bundled frozen OCR runtime.
        environment["DLMS_TESSERACT_EXECUTABLE"] = "/nonexistent/dlms-ocr-probe"
        modes = [("desktop", ["--browser"])]
        if lan:
            modes.append(("lan", ["--host", "0.0.0.0", "--no-browser"]))
        for mode, args in modes:
            _assert_port_available()
            with (work / f"{mode}.log").open("wb") as log:
                process = subprocess.Popen([str(image), *args], cwd=work, env=environment,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                client = SmokeHttpClient()
                try:
                    _wait_for_server(process, client)
                    _assert_smoke_routes(client, version)
                    if mode == "desktop":
                        deadline = time.monotonic() + 10
                        while not opened.exists() and time.monotonic() < deadline:
                            time.sleep(0.05)
                        if not opened.exists() or SERVER_URL not in opened.read_text():
                            raise RuntimeError("Desktop launch did not dispatch the local browser URL")
                        verify_browser_environment(opened.read_text(), str(host_libraries))
                        result["browser_host_library_environment"] = "PASS"
                        result["browser_dispatch_stub"] = "PASS"
                        result.update(ocr_workflows(client))
                        opened.unlink()
                    else:
                        if opened.exists():
                            raise RuntimeError("--no-browser unexpectedly launched the browser")
                        result["lan_arguments_loopback_http"] = "PASS"
                    if mode == "lan":
                        # LAN mode intentionally disables the desktop shutdown
                        # endpoint. Preserve that boundary and stop our own server.
                        status, _ = _request("/api/shutdown", "POST", client=client,
                                             headers={"X-CSRFToken": client.csrf_token(), "Origin": SERVER_URL})
                        if status != 403:
                            raise RuntimeError(f"LAN desktop shutdown should be denied, got {status}")
                        result["lan_desktop_shutdown_denied"] = "PASS"
                        process.terminate()
                        process.wait(timeout=5)
                    else:
                        _shutdown_cleanly(process, client, "linux-x86_64")
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
            if mode == "lan" and "0.0.0.0" not in (work / "lan.log").read_text():
                raise RuntimeError("LAN bind was not confirmed by startup diagnostics")
        if not (data_root / ".dlms-data-root").is_file():
            raise RuntimeError("AppImage did not use the external data root")
        result["external_data_root"] = "PASS"
    if sha256_file(image) != digest:
        raise RuntimeError("Evaluation modified the AppImage")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--lan", action="store_true", help="briefly bind synthetic test server to all interfaces")
    parser.add_argument("--report", type=Path, required=True, help="new JSON evidence file")
    args = parser.parse_args(argv)
    # Reserve evidence before launching; never silently overwrite earlier UAT.
    with args.report.open("x", encoding="utf-8") as report:
        try:
            result = evaluate(args.image, args.expected_version, lan=args.lan)
        except Exception as exc:
            json.dump({"status": "FAILED", "error": str(exc)}, report, indent=2)
            raise
        json.dump({"status": "PASSED", **result}, report, indent=2)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
