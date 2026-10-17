"""Desktop backup waits for a shared-permit settings write."""
from __future__ import annotations

import argparse
import http.client
import io
import json
from http.cookies import SimpleCookie
import threading
import time
import zipfile

from tests.gate1.qt_checks import QtChecks


def until(q, predicate, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        q.delay(0.08)
    raise TimeoutError("Settings/backup overlap checkpoint missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, pause_settings_write=True)
    result = {}
    try:
        port = q.window.port
        headers = {"Host": f"127.0.0.1:{port}", "X-DLMS-Desktop-Token": q.window.nonce}
        opener = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
        opener.request("GET", "/settings/backup", headers=headers)
        page = opener.getresponse()
        cookies = SimpleCookie()
        for key, value in page.getheaders():
            if key.lower() == "set-cookie":
                cookies.load(value)
        page.read(); opener.close()
        csrf = cookies["dlms_csrf_token"].value
        cookie = "; ".join(f"{name}={morsel.value}" for name, morsel in cookies.items())
        q.go("/settings/appearance")
        q.js("document.getElementById('appearanceTheme').value='ethereal'; document.querySelector('form[action=\"/settings/appearance/save\"] button[type=submit]').click(); true")
        paused = q.paths["root"] / "blockc-settings-write-paused.json"
        until(q, paused.exists)
        result["writer_checkpoint"] = json.loads(paused.read_text())
        backup = {}

        def request_backup():
            client = http.client.HTTPConnection("127.0.0.1", port, timeout=25)
            try:
                client.request("POST", "/settings/backup/create", headers={**headers,
                    "Origin": f"http://127.0.0.1:{port}", "X-CSRFToken": csrf,
                    "Cookie": cookie, "Content-Length": "0"})
                response = client.getresponse()
                backup["status"], backup["bytes"] = response.status, response.read()
            except BaseException as exc:
                backup["error"] = str(exc)
            finally:
                client.close()

        worker = threading.Thread(target=request_backup, daemon=True)
        worker.start()
        until(q, lambda: (q.paths["root"] / "blockc-backup-request-entered.json").exists())
        result["backup_entered_during_write"] = worker.is_alive()
        (q.paths["root"] / "blockc-settings-write-release").write_text("release\n")
        q.wait("location.pathname === '/settings/appearance' && location.search.includes('saved=1')")
        worker.join(timeout=25)
        result["backup_status"] = backup.get("status")
        if backup.get("status") == 200:
            with zipfile.ZipFile(io.BytesIO(backup["bytes"])) as archive:
                result["zip_crc"] = archive.testzip() is None
                result["snapshot_theme"] = json.loads(archive.read("DLMS_DATA/config/portal.json"))["theme"]
        result["live_theme"] = json.loads((q.paths["backend"] / "config" / "portal.json").read_text())["theme"]
        result["pass"] = bool(result["writer_checkpoint"]["theme"] == "ethereal"
            and result["backup_entered_during_write"] and result["backup_status"] == 200
            and result.get("zip_crc") and result.get("snapshot_theme") == result["live_theme"] == "ethereal")
    finally:
        (q.paths["root"] / "blockc-settings-overlap.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
