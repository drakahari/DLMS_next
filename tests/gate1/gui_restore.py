"""Restore a synthetic backup through the embedded Qt page into a second profile."""
from __future__ import annotations

import base64
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import traceback

from desktop.isolation import profile_paths
from tests.gate1.qt_checks import QtChecks


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def facts(root: Path):
    db = root / "results.db"
    with sqlite3.connect(db) as conn:
        quizzes = conn.execute("SELECT title FROM quizzes ORDER BY title").fetchall()
        responses = conn.execute("SELECT count(*) FROM study_responses WHERE kind='response'").fetchone()[0]
        version = conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
    files = {}
    for folder in ("data", "quizzes"):
        for path in (root / folder).glob("*"):
            if path.is_file() and not path.name.startswith("parse_log_"):
                files[str(path.relative_to(root))] = digest(path)
    return {"quizzes": quizzes, "responses": responses, "schema": version, "content_hashes": files}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="restore02")
    args = parser.parse_args()
    source = profile_paths("foundation01", create=False)
    archive = max(source["downloads"].glob("DLMS-backup-*.zip"), key=lambda p: p.stat().st_mtime)
    before = facts(source["backend"])
    q = QtChecks(args.profile)
    result = {"source_backup": archive.name, "source_sha256": digest(archive), "before": before}
    try:
        q.go("/settings/backup")
        encoded = base64.b64encode(archive.read_bytes()).decode("ascii")
        script = """(async()=>{const bin=atob(DATA),bytes=new Uint8Array(bin.length);
        for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
        const form=new FormData();form.append('backup_file',new File([bytes],'synthetic-backup.zip',{type:'application/zip'}));
        const response=await fetch('/settings/backup/restore/stage',{method:'POST',body:form,credentials:'same-origin'});
        const html=await response.text(),page=new DOMParser().parseFromString(html,'text/html');
        window.__gate1Restore=JSON.stringify({status:response.status,url:response.url,confirm:page.querySelector('form[action*=\"/restore/confirm/\"]')?.getAttribute('action'),text:html.slice(0,250)});})()""".replace("DATA", json.dumps(encoded))
        q.js(script)
        q.wait("!!window.__gate1Restore", 30)
        stage = json.loads(q.js("window.__gate1Restore"))
        result["stage"] = stage
        if stage["status"] != 200 or not stage.get("confirm"):
            raise RuntimeError("Backup did not reach the confirmation page")
        result["confirmation_visible"] = "Confirm Restore" in stage["text"]
        q.js("""(async()=>{const response=await fetch(ACTION,{method:'POST',credentials:'same-origin'});
        window.__gate1Confirmed=JSON.stringify({status:response.status,url:response.url,text:(await response.text()).slice(0,500)});})()""".replace("ACTION", json.dumps(stage["confirm"])))
        q.wait("!!window.__gate1Confirmed", 30)
        result["confirmation"] = json.loads(q.js("window.__gate1Confirmed"))
        q.go("/settings/backup")
        result["completion_visible"] = "Restore Complete" in result["confirmation"]["text"]
        q.go("/library")
        result["restored_library_visible"] = q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        result["screenshot"] = str(q.screenshot("restored-library.png"))
        result["after"] = facts(q.paths["backend"])
        result["data_equal"] = before == result["after"]
        result["status"] = "pass" if (result["data_equal"]
                                      and result["before"]["schema"] == 12
                                      and result["confirmation_visible"]
                                      and result["completion_visible"]
                                      and result["restored_library_visible"]) else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "restore-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
