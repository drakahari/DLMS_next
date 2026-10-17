"""Representative Qt authoring organization, scope, plan and credential state."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback
import time

from tests.gate1.qt_checks import QtChecks


def until(q, predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        q.delay(0.1)
    raise TimeoutError("Qt parity mutation did not settle")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    report = {}
    try:
        db = q.paths["backend"] / "results.db"
        with sqlite3.connect(db) as conn:
            original = {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                        for table in ("questions", "choices", "attempts", "study_responses")}
        q.go("/library")
        report["source_quiz_visible"] = q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        if not q.js("document.body.innerText.includes('Block C Folder')"):
            q.js("(()=>{const f=document.querySelector('form[action=\"/add_quiz_folder\"]');f.querySelector('input[name=folder]').value='Block C Folder';f.requestSubmit();return true})()")
            q.wait("location.pathname === '/library' && document.body.innerText.includes('Block C Folder')")
        report["folder_created"] = q.js("document.body.innerText.includes('Block C Folder')")
        registry = json.loads((q.paths["backend"] / "config" / "quizzes.json").read_text())
        if next(x["folder"] for x in registry if x["id"] == 1) != "Block C Folder":
            q.js("(()=>{const f=[...document.querySelectorAll('form[action=\"/move_quiz_folder\"]')].find(x=>x.querySelector('input[name=id]')?.value==='1');f.querySelector('select[name=folder]').value='Block C Folder';f.requestSubmit();return true})()")
            until(q, lambda: next(x["folder"] for x in json.loads((q.paths["backend"] / "config" / "quizzes.json").read_text()) if x["id"] == 1) == "Block C Folder")
        registry = json.loads((q.paths["backend"] / "config" / "quizzes.json").read_text())
        report["moved_folder"] = next(x["folder"] for x in registry if x["id"] == 1)
        report["library_screenshot"] = str(q.screenshot("blockc-library-folder.png"))

        q.go("/learning-scope")
        report["scope_folder_visible"] = q.js("document.body.innerText.includes('Block C Folder')")
        if not q.js("document.body.innerText.includes('1 folder excluded')"):
            q.js("(()=>{const f=[...document.forms].find(x=>x.querySelector('input[name=folder]')?.value==='Block C Folder');f.requestSubmit();return true})()")
            q.wait("location.pathname === '/learning-scope' && document.body.innerText.includes('1 folder excluded')")
        report["scope_excluded"] = q.js("document.body.innerText.includes('1 folder excluded')")
        q.js("(()=>{const f=[...document.forms].find(x=>x.querySelector('input[name=folder]')?.value==='Block C Folder');f.requestSubmit();return true})()")
        q.wait("location.pathname === '/learning-scope' && document.body.innerText.includes('0 folders excluded')")
        report["scope_reincluded"] = q.js("document.body.innerText.includes('0 folders excluded')")

        q.go("/exam-plans/new")
        report["plan_form_folders"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('input[name=folders]')].map(x=>({value:x.value,label:x.parentElement?.innerText})))"))
        q.js("(()=>{const f=document.getElementById('examPlanForm');f.querySelector('[name=name]').value='Block C Synthetic Plan';f.querySelector('[name=exam_date]').value='2027-05-01';f.querySelector('[name=calendar_timezone]').value='America/Chicago';const folder=[...f.querySelectorAll('[name=folders]')].find(x=>x.parentElement?.innerText.includes('Block C Folder'));folder.checked=true;[...f.querySelectorAll('[name=weekdays]')].filter(x=>['0','2','4'].includes(x.value)).forEach(x=>x.checked=true);f.requestSubmit();return true})()")
        q.wait("location.pathname.startsWith('/exam-plans/') && location.pathname !== '/exam-plans/new'", 15)
        report["plan_detail"] = q.js("JSON.stringify({path:location.pathname,text:document.body.innerText.slice(-1600)})")
        report["plan_screenshot"] = str(q.screenshot("blockc-exam-plan.png"))
        with sqlite3.connect(db) as conn:
            rows = conn.execute("SELECT id,config_json FROM exam_plans").fetchall()
            report["plan_count"] = len(rows)
            report["plan_config"] = [json.loads(row[1]) for row in rows]

        q.go("/certifications")
        cert_link = q.js("[...document.querySelectorAll('a[href^=\"/certifications/\"]')].find(a=>a.innerText.includes('Synthetic credential'))?.getAttribute('href')")
        q.go(cert_link)
        report["certification_text"] = q.js("document.body.innerText.slice(-2200)")
        report["certification_screenshot"] = str(q.screenshot("blockc-certification.png"))
        q.go("/history")
        report["exam_history"] = q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        q.go("/study-history")
        report["study_history"] = q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        q.go("/learning-intelligence")
        report["intelligence"] = q.js("document.body.innerText.includes('Topics, Mastery')")
        with sqlite3.connect(db) as conn:
            report["canonical_tables_unchanged"] = all(
                conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() == original[table]
                for table in original)
        report["pass"] = bool(report["source_quiz_visible"] and report["folder_created"]
            and report["moved_folder"] == "Block C Folder" and report["scope_folder_visible"]
            and report["scope_excluded"] and report["scope_reincluded"] and
            report["plan_count"] >= 1 and "Block C Synthetic Plan" in report["plan_detail"]
            and "Synthetic workshop" in report["certification_text"] and
            "8 h 0 min" in report["certification_text"] and report["exam_history"]
            and report["study_history"] and report["intelligence"] and report["canonical_tables_unchanged"])
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "blockc-parity-core.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
