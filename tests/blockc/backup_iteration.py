"""Close a Desktop backup after WSGI iteration begins, then reuse its gate."""
from __future__ import annotations

import argparse
import http.client
import io
import json
from http.cookies import SimpleCookie
from pathlib import Path
import socket
import sqlite3
import time
import zipfile

from tests.gate1.qt_checks import QtChecks


def until(q, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        q.delay(0.08)
    raise TimeoutError("Desktop backup iteration checkpoint did not arrive")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, pause_backup_iteration=True)
    report = {}
    raw = None
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
        page.read()
        opener.close()
        csrf = cookies["dlms_csrf_token"].value
        cookie = "; ".join(f"{name}={morsel.value}" for name, morsel in cookies.items())
        post = {**headers, "Origin": f"http://127.0.0.1:{port}",
                "X-CSRFToken": csrf, "Cookie": cookie, "Content-Length": "0"}
        raw = socket.create_connection(("127.0.0.1", port), timeout=8)
        request = "POST /settings/backup/create HTTP/1.1\r\n" + "\r\n".join(
            f"{key}: {value}" for key, value in post.items()) + "\r\nConnection: close\r\n\r\n"
        raw.sendall(request.encode("ascii"))
        entered = q.paths["root"] / "blockc-backup-iteration.json"
        until(q, entered.exists)
        report["entered_iteration_before_close"] = json.loads(entered.read_text())["entered"]
        raw.close()
        raw = None
        (q.paths["root"] / "blockc-backup-iteration-release").write_text("release\n")
        closed = q.paths["root"] / "blockc-backup-iterable-closed.json"
        until(q, closed.exists)
        report["iterable_closed"] = json.loads(closed.read_text())["closed"]
        second = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        second.request("POST", "/settings/backup/create", headers=post)
        response = second.getresponse()
        payload = response.read()
        report["next_backup_status"] = response.status
        second.close()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            report["next_backup_zip_crc"] = archive.testzip() is None
            report["next_backup_members"] = len(archive.namelist())
        # A read-only context lookup would not establish that the managed
        # action gate is usable after the abandoned response.
        registry = json.loads((q.paths["backend"] / "config" / "quizzes.json").read_text())
        quiz = next(x for x in registry if x.get("html"))
        q.go(f"/quizzes/{quiz['html']}")
        if q.js("!!document.querySelector('.quiz-recovery-resume')"):
            q.js("document.querySelector('.quiz-recovery-resume').click(); true")
        else:
            q.wait("document.querySelector('.study-mode-btn')?.disabled === false")
            q.js("document.querySelector('.study-mode-btn').click(); true")
        q.wait("document.getElementById('studyAnkiBtn')?.style.display !== 'none'", 15)
        with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
            before = conn.execute("SELECT count(*) FROM review_mark_actions").fetchone()[0]
        q.js("document.getElementById('studyAnkiBtn').click(); true")
        q.wait("/saved in DLMS|cleanup failed/.test(document.getElementById('reviewMarkStatus')?.innerText || '')", 20)
        report["managed_action_message"] = q.js("document.getElementById('reviewMarkStatus').innerText")
        with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
            report["managed_action_rows_added"] = conn.execute("SELECT count(*) FROM review_mark_actions").fetchone()[0] - before
        report["pass"] = (report["entered_iteration_before_close"] and report["iterable_closed"]
                          and report["next_backup_status"] == 200 and report["next_backup_zip_crc"]
                          and report["managed_action_rows_added"] == 1)
    finally:
        if raw is not None:
            raw.close()
        (q.paths["root"] / "blockc-backup-iteration-result.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
