"""Fail one Study event save, restart the Qt profile, and retry it."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import traceback
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def responses(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT count(*) FROM study_responses WHERE kind='response'").fetchone()[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("create", "reopen"), required=True)
    parser.add_argument("--profile", default="studypending01")
    parser.add_argument("--crash-after-pending", action="store_true")
    args = parser.parse_args()
    q = QtChecks(args.profile)
    result = {"phase": args.phase}
    try:
        url = urlsplit(json.loads((q.paths["root"] / "foundation-create.json").read_text())["quiz_url"]).path
        q.go(url)
        db = q.paths["backend"] / "results.db"
        if args.phase == "create":
            if q.js("!!document.querySelector('.quiz-recovery-start-over')"):
                q.js("window.confirm=()=>true; document.querySelector('.quiz-recovery-start-over').click(); true")
                q.wait("document.querySelector('.quiz-recovery-panel')?.hidden === true")
            result["responses_before"] = responses(db)
            q.js("document.querySelector('.study-mode-btn').click(); true")
            q.wait("document.querySelector('button.choice') !== null")
            q.window.interceptor.blocked_internal_paths.add("/_desktop/recovery/action")
            q.js("document.querySelector('button.choice').click(); true")
            q.wait("(()=>{let r=JSON.parse(localStorage.getItem('dlms.quiz-progress.v1:'+window.QUIZ_ID)||'null');return r?.unacknowledgedStudyEvents?.length===1})()", 15)
            result["browser_pending"] = True
            result["save_status_text"] = q.js("document.querySelector('#studyLearningEventStatus')?.innerText || ''")
            result["durable_action_files"] = len(list((q.paths["root"] / "durable-actions").glob("*.json")))
            result["responses_with_failed_save"] = responses(db)
            result["screenshot"] = str(q.screenshot("study-pending.png"))
            result["status"] = "pass" if result["responses_before"] == result["responses_with_failed_save"] else "fail"
        else:
            q.wait("!!document.querySelector('.quiz-recovery-resume')")
            result["pending_before_resume"] = q.js("(()=>{let r=JSON.parse(localStorage.getItem('dlms.quiz-progress.v1:'+window.QUIZ_ID)||'null');return r?.unacknowledgedStudyEvents?.length===1})()")
            q.js("document.querySelector('.quiz-recovery-resume').click(); true")
            q.wait("(()=>{let r=JSON.parse(localStorage.getItem('dlms.quiz-progress.v1:'+window.QUIZ_ID)||'null');return r && r.unacknowledgedStudyEvents.length===0})()", 20)
            result["responses_after"] = responses(db)
            result["screenshot"] = str(q.screenshot("study-pending-recovered.png"))
            result["status"] = "pass" if result["pending_before_resume"] and result["responses_after"] == 2 else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / f"study-pending-{args.phase}.json").write_text(json.dumps(result, indent=2) + "\n")
        if args.crash_after_pending and args.phase == "create" and result["status"] == "pass":
            os.kill(os.getpid(), signal.SIGKILL)  # exact disposable GUI process
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
