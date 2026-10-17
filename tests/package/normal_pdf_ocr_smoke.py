"""Exercise PDF and OCR routes through the normal frozen executable.

This sends requests only to the backend owned by the launched synthetic profile.
It does not automate the desktop or assert rendered WebEngine behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from tests.package.normal_local_settings_smoke import (
    backend_nonce, descendants, request, starttime, stop_exact_owned,
)


def multipart(field: str, name: str, media: str, payload: bytes, values: dict[str, str]):
    boundary = "dlmsdesktop" + uuid.uuid4().hex
    parts = []
    for key, value in values.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
        f"filename=\"{name}\"\r\nContent-Type: {media}\r\n\r\n".encode()
        + payload + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("exe", "data_root", "cwd", "output", "pdf", "png"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    requested_root = args.data_root.absolute()
    project = Path(__file__).resolve().parents[2]
    allowed = (project / ".gate1" / "packaging").resolve()
    if ".." in requested_root.parts or not requested_root.is_relative_to(allowed) or requested_root == allowed:
        raise ValueError("Data root must be under the project's ignored package test area")
    for component in (requested_root, *requested_root.parents):
        if component == allowed.parent:
            break
        if component.is_symlink():
            raise ValueError(f"Symlink in disposable root: {component}")
    if requested_root.resolve(strict=True) != requested_root:
        raise ValueError("Data root must use its canonical path")
    marker = requested_root / ".dlms-desktop-disposable.json"
    if marker.is_symlink() or not marker.is_file() or json.loads(marker.read_text()).get("kind") != (
        "dlms-desktop-fedora-package-feasibility"
    ):
        raise ValueError("The package data root is not a marked disposable fixture")
    for name in ("exe", "data_root", "cwd", "output", "pdf", "png"):
        setattr(args, name, getattr(args, name).resolve())
    if not (args.exe.is_file() and args.data_root.is_dir() and args.cwd.is_dir()
            and args.pdf.is_file() and args.png.is_file() and not args.output.exists()):
        raise ValueError("Package, fixtures, cwd or fresh output path is unavailable")
    if (args.data_root / "profiles" / args.profile).exists():
        raise ValueError("The synthetic test profile already exists")
    args.output.mkdir(parents=True)
    environment = args.output / "environment"
    env = {"PATH": "/nonexistent", "LANG": "C.UTF-8", "QT_QPA_PLATFORM": "offscreen"}
    for key, relative in (("HOME", "home"), ("XDG_DATA_HOME", "xdg/data"),
                          ("XDG_CONFIG_HOME", "xdg/config"), ("XDG_CACHE_HOME", "xdg/cache"),
                          ("TMPDIR", "tmp"), ("XDG_RUNTIME_DIR", "xdg/runtime")):
        target = environment / relative
        target.mkdir(parents=True, mode=0o700)
        target.chmod(0o700)
        env[key] = str(target)
    with (args.output / "launcher.log").open("w") as log:
        process = subprocess.Popen([str(args.exe), "--profile", args.profile,
                                    "--data-root", str(args.data_root)], cwd=args.cwd,
                                   env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        observed = {process.pid: starttime(process.pid)}
        try:
            manifest_path = args.data_root / "profiles" / args.profile / "desktop-profile.json"
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                assert process.poll() is None, f"Packaged launcher exited {process.returncode}"
                observed.update({pid: starttime(pid) for pid in descendants(process.pid)})
                owner = backend_nonce(process.pid)
                if owner and manifest_path.is_file():
                    port = json.loads(manifest_path.read_text())["port"]
                    try:
                        if request(port, owner[1], "GET", "/_desktop/ready")[0] == 200:
                            break
                    except OSError:
                        pass
                time.sleep(0.1)
            else:
                raise TimeoutError("Normal packaged backend did not become ready")
            nonce = owner[1]
            origin = f"http://127.0.0.1:{port}"
            status, token_body, headers = request(port, nonce, "GET", "/api/csrf-token",
                extra_headers={"X-DLMS-CSRF-Refresh": "1", "Origin": origin}, include_headers=True)
            assert status == 200
            csrf = json.loads(token_body)["csrf_token"]
            cookie = "; ".join(value.split(";", 1)[0] for key, value in headers
                               if key.lower() == "set-cookie")
            assert cookie
            common = {"Origin": origin, "Referer": origin + "/pdf-import", "Cookie": cookie,
                      "X-CSRFToken": csrf}

            def post(path: str, body: bytes, content_type: str):
                return request(port, nonce, "POST", path, body=body, include_headers=True,
                               extra_headers=common | {"Content-Type": content_type})

            pdf_bytes, png_bytes = args.pdf.read_bytes(), args.png.read_bytes()
            body, media = multipart("pdf_file", args.pdf.name, "application/pdf", pdf_bytes,
                {"rights_ok": "on", "quiz_title": "Normal Package Scanned PDF",
                 "pdf_content_type": "question_bank"})
            pdf_status, _, pdf_headers = post("/pdf-import/analyze", body, media)
            assert pdf_status == 302, pdf_status
            pdf_location = dict(pdf_headers)["Location"]
            assert pdf_location.startswith("/pdf-import/ocr/"), pdf_location
            pdf_offer_status, pdf_offer = request(port, nonce, "GET", pdf_location)
            assert pdf_offer_status == 200 and b"OCR" in pdf_offer
            pdf_id = pdf_location.rsplit("/", 1)[-1]
            pdf_start_status, _, pdf_start_headers = post(
                f"/pdf-import/ocr/{pdf_id}/start", b"ocr_pages=1", "application/x-www-form-urlencoded")
            assert pdf_start_status == 302, pdf_start_status
            pdf_process_location = dict(pdf_start_headers)["Location"]
            assert pdf_process_location == f"/pdf-import/ocr/{pdf_id}/process", pdf_process_location
            pdf_next_status, pdf_next_body, _ = post(
                f"/pdf-import/ocr/{pdf_id}/process/next", b"", "application/x-www-form-urlencoded")
            assert pdf_next_status == 200, (pdf_next_status, pdf_next_body[:250])
            pdf_processed = json.loads(pdf_next_body)
            assert pdf_processed["status"] == "complete" and pdf_processed["has_results"], pdf_processed
            pdf_draft_path = (args.data_root / "profiles" / args.profile / "backend"
                              / "pdf_import_drafts" / f"{pdf_id}.json")
            pdf_draft = json.loads(pdf_draft_path.read_text())
            assert pdf_draft["questions"] and "Which shape has three sides?" in json.dumps(pdf_draft["questions"])

            body, media = multipart("screenshots", args.png.name, "image/png", png_bytes,
                {"rights_ok": "on", "quiz_title": "Normal Package PNG OCR"})
            png_status, _, png_headers = post("/pdf-import/screenshots", body, media)
            assert png_status == 302, png_status
            png_location = dict(png_headers)["Location"]
            assert png_location.startswith("/pdf-import/screenshots/process/"), png_location
            draft_id = png_location.rsplit("/", 1)[-1]
            next_status, next_body, _ = post(
                f"/pdf-import/screenshots/process/{draft_id}/next", b"", "application/x-www-form-urlencoded")
            assert next_status == 200, (next_status, next_body[:250])
            response = json.loads(next_body)
            assert response["status"] == "complete" and response["has_results"], response
            draft_path = args.data_root / "profiles" / args.profile / "backend" / "pdf_import_drafts" / f"{draft_id}.json"
            draft = json.loads(draft_path.read_text())
            assert draft["questions"] and "Which shape has three sides?" in json.dumps(draft["questions"])
            assert request(port, nonce, "POST", "/api/shutdown")[0] == 200
            assert process.wait(timeout=25) == 0
            result = {"normal_executable": str(args.exe), "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                      "png_sha256": hashlib.sha256(png_bytes).hexdigest(),
                      "pdf_offer_status": pdf_offer_status, "png_ocr_status": response["status"],
                      "pdf_ocr_status": pdf_processed["status"],
                      "pdf_question_count": len(pdf_draft["questions"]),
                      "png_question_count": len(draft["questions"]), "no_host_tools_in_path": True,
                      "scope": "Normal frozen backend routes; no native file chooser or rendered UI assertion"}
            (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
        finally:
            residual = stop_exact_owned(process, observed)
            if residual:
                raise RuntimeError(f"Exact owned processes survived: {residual}")


if __name__ == "__main__":
    main()
