"""Fail a synthetic Exam save, restart, then recover it in Qt WebEngine."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def attempts(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT count(*) FROM attempts").fetchone()[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("create", "reopen"), required=True)
    parser.add_argument("--profile", default="exam01")
    args = parser.parse_args()
    q = QtChecks(args.profile)
    result = {"phase": args.phase}
    try:
        url = urlsplit(json.loads((q.paths["root"] / "foundation-create.json").read_text())["quiz_url"]).path
        q.go(url)
        q.wait("quizRecoveryReady===true && document.querySelector('.exam-mode-btn')?.disabled===false")
        if args.phase == "create":
            if q.js("!!document.querySelector('.quiz-recovery-start-over')"):
                q.js("window.confirm=()=>true; document.querySelector('.quiz-recovery-start-over').click(); true")
                q.wait("document.querySelector('.quiz-recovery-panel')?.hidden === true")
            # Switching a restored Study session into Exam asks for a browser
            # confirmation. Answer it inside this synthetic page so the
            # synchronous JS driver does not wait behind a native modal.
            q.js("window.confirm=()=>true; document.querySelector('.exam-mode-btn').click(); true")
            q.wait("document.querySelector('button.choice') !== null")
            q.js("document.querySelector('button.choice').click(); true")
            q.window.interceptor.blocked_internal_paths.add("/_desktop/recovery/action")
            q.js("window.confirm=()=>true; document.getElementById('submitBtn').click(); true")
            q.wait("(()=>{let r=JSON.parse(localStorage.getItem('dlms.quiz-progress.v1:'+window.QUIZ_ID)||'null');return !!r?.pendingAttempt})()", 15)
            result["pending_attempt_browser"] = True
            result["attempts_before_restart"] = attempts(q.paths["backend"] / "results.db")
            result["screenshot"] = str(q.screenshot("exam-pending.png"))
            result["status"] = "pass" if result["attempts_before_restart"] == 0 else "fail"
        else:
            q.wait("!!document.querySelector('.quiz-recovery-resume')")
            result["pending_before_resume"] = q.js("(()=>{let r=JSON.parse(localStorage.getItem('dlms.quiz-progress.v1:'+window.QUIZ_ID)||'null');return !!r?.pendingAttempt})()")
            q.js("document.querySelector('.quiz-recovery-resume').click(); true")
            # Retry is driven by the captured application's recovery controller.
            q.wait("document.body.innerText.includes('Exam Result') || document.body.innerText.includes('Exam Results')", 20)
            q.wait("!JSON.parse(localStorage.getItem('dlms.quiz-progress.v1:'+window.QUIZ_ID)||'null')?.pendingAttempt", 20)
            result["attempts_after_recovery"] = attempts(q.paths["backend"] / "results.db")
            result["screenshot"] = str(q.screenshot("exam-recovered.png"))
            result["status"] = "pass" if result["pending_before_resume"] and result["attempts_after_recovery"] == 1 else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / f"exam-{args.phase}-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
