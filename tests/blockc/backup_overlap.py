"""A Desktop backup waits for a paused supported quiz publication."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
from http.cookies import SimpleCookie
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import zipfile

from desktop.isolation import PROJECT
from tests.gate1.qt_checks import QtChecks


def until(q, predicate, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        q.delay(0.08)
    raise TimeoutError("Concurrent backup checkpoint did not arrive")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, pause_publication=True)
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
        page.read()
        opener.close()
        csrf = cookies["dlms_csrf_token"].value
        cookie = "; ".join(f"{name}={morsel.value}" for name, morsel in cookies.items())
        content = (PROJECT / "fixtures" / "gate1-neutral-quiz.txt").read_text()
        script = """(async()=>{const form=new FormData();
          form.append('quiz_title','Block C Concurrent Quiz');
          form.append('file',new File([TEXT],'concurrent.txt',{type:'text/plain'}));
          const cookie=document.cookie.split('; ').find(x=>x.startsWith('dlms_csrf_token='));
          form.append('csrf_token',decodeURIComponent(cookie?.split('=')[1]||''));
          const response=await fetch('/process',{method:'POST',body:form,credentials:'same-origin'});
          window.__blockcCreate={status:response.status,url:response.url};})()""".replace("TEXT", json.dumps(content))
        q.js("window.__blockcCreate=null; true")
        q.js(script)
        until(q, lambda: (q.paths["root"] / "blockc-publication-paused.json").exists())
        result["publication_paused"] = json.loads((q.paths["root"] / "blockc-publication-paused.json").read_text())
        backup = {}

        def request_backup():
            client = http.client.HTTPConnection("127.0.0.1", port, timeout=25)
            try:
                client.request("POST", "/settings/backup/create", headers={**headers,
                    "Origin": f"http://127.0.0.1:{port}", "X-CSRFToken": csrf,
                    "Cookie": cookie, "Content-Length": "0"})
                response = client.getresponse()
                backup["status"] = response.status
                backup["bytes"] = response.read()
            except BaseException as exc:
                backup["error"] = str(exc)
            finally:
                client.close()

        thread = threading.Thread(target=request_backup, daemon=True)
        thread.start()
        until(q, lambda: (q.paths["root"] / "blockc-backup-request-entered.json").exists())
        result["backup_entered_while_publication_paused"] = thread.is_alive()
        (q.paths["root"] / "blockc-publication-release").write_text("release\n")
        until(q, lambda: q.js("!!window.__blockcCreate"))
        thread.join(timeout=25)
        result["creation"] = json.loads(q.js("JSON.stringify(window.__blockcCreate)"))
        result["backup_status"] = backup.get("status")
        if backup.get("status") == 200:
            payload = backup["bytes"]
            snapshot = q.paths["root"] / "blockc-overlap-snapshot.zip"
            snapshot.write_bytes(payload)
            result["snapshot_path"] = str(snapshot)
            result["snapshot_sha256"] = hashlib.sha256(payload).hexdigest()
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                result["zip_crc"] = archive.testzip() is None
                registry = json.loads(archive.read("DLMS_DATA/config/quizzes.json"))
                quiz = next(x for x in registry if x["title"] == "Block C Concurrent Quiz")
                stem = Path(quiz["html"]).stem
                runtime = json.loads(archive.read(f"DLMS_DATA/data/{stem}.json"))
                html = archive.read(f"DLMS_DATA/quizzes/{quiz['html']}")
                result["archive_live_hashes"] = {}
                for member, live in (("DLMS_DATA/config/quizzes.json", q.paths["backend"] / "config" / "quizzes.json"),
                                     (f"DLMS_DATA/data/{stem}.json", q.paths["backend"] / "data" / f"{stem}.json"),
                                     (f"DLMS_DATA/quizzes/{quiz['html']}", q.paths["backend"] / "quizzes" / quiz["html"])):
                    result["archive_live_hashes"][member] = {
                        "archive": hashlib.sha256(archive.read(member)).hexdigest(),
                        "live": hashlib.sha256(live.read_bytes()).hexdigest()}
                result["file_hashes_equal"] = all(pair["archive"] == pair["live"]
                                                  for pair in result["archive_live_hashes"].values())
                with tempfile.TemporaryDirectory(dir=q.paths["tmp"]) as temporary:
                    db = Path(temporary) / "results.db"
                    db.write_bytes(archive.read("DLMS_DATA/results.db"))
                    with sqlite3.connect(db) as conn:
                        row = conn.execute("SELECT id,title FROM quizzes WHERE id=?", (quiz["id"],)).fetchone()
                        choices = conn.execute("SELECT c.label,c.text,c.is_correct,c.choice_order FROM choices c JOIN questions q ON q.id=c.question_id WHERE q.quiz_id=? ORDER BY q.id,c.choice_order", (quiz["id"],)).fetchall()
                result["relationship"] = {"registry_id": quiz["id"], "db_row": row,
                    "runtime_questions": len(runtime), "html_bytes": len(html), "choices": choices}
                result["content_fidelity"] = (row == (quiz["id"], quiz["title"])
                    and len(runtime) == 4 and len(html) > 100
                    and any(label == "B" and text == "Four" and correct == 1 for label,text,correct,order in choices))
        result["pass"] = bool(result["publication_paused"]["stage"] == "db_committed"
            and result["backup_entered_while_publication_paused"] and
            result["creation"]["status"] == 200 and result["backup_status"] == 200 and
            result.get("zip_crc") and result.get("content_fidelity") and result.get("file_hashes_equal"))
    finally:
        (q.paths["root"] / "blockc-backup-overlap.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
