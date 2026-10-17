"""Real Qt committed+cleaned Exam with withheld acknowledgment and changed source."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def durable(db, attempt_id):
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        columns = {row[1] for row in conn.execute("PRAGMA table_info(attempts)")}
        identity = "attempt_id" if "attempt_id" in columns else "id"
        attempts = [dict(row) for row in conn.execute(
            f"SELECT * FROM attempts WHERE CAST({identity} AS TEXT)=?", (attempt_id,))]
        events = [dict(row) for row in conn.execute(
            "SELECT * FROM learning_events WHERE attempt_id=? ORDER BY id", (attempt_id,))]
    return {"attempts": attempts, "events": events}


def pending(q, quiz_id):
    raw = q.js(f"localStorage.getItem('dlms.quiz-progress.v1:'+{quiz_id})")
    parsed = json.loads(raw or "null")
    attempt = parsed.get("pendingAttempt") if isinstance(parsed, dict) else None
    return {"present": bool(attempt), "attempt_id": attempt.get("attemptId") if attempt else None,
            "pending_attempt_hash": hashlib.sha256(json.dumps(attempt, sort_keys=True).encode()).hexdigest()
            if attempt else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, drop_cleaned_exam_reply=True)
    root = q.paths["root"]
    db = q.paths["backend"] / "results.db"
    report = {"profile": args.profile}
    try:
        fixture = json.loads((root / "foundation-create.json").read_text())
        quiz_id = fixture["quiz_id"]
        q.go(urlsplit(fixture["quiz_url"]).path)
        if q.js("!!document.querySelector('.quiz-recovery-start-over')"):
            q.js("window.confirm=()=>true; document.querySelector('.quiz-recovery-start-over').click(); true")
            q.wait("document.querySelector('.quiz-recovery-panel')?.hidden === true")
        q.js("document.querySelector('.exam-mode-btn').click(); true")
        q.wait("document.querySelector('button.choice') !== null")
        q.js("document.querySelector('button.choice').click(); true")
        q.js("window.__firstActionStatus=null; window.__nativeActionFetch=window.fetch.bind(window);"
             "window.fetch=async (...args)=>{const r=await window.__nativeActionFetch(...args);"
             "if(String(args[0]).includes('/_desktop/recovery/action') && window.__firstActionStatus===null)"
             "window.__firstActionStatus=r.status; return r}; true")
        q.js("window.confirm=()=>true; document.getElementById('submitBtn').click(); true")
        q.wait("document.getElementById('result')?.innerText.includes('not confirmed as retained or saved')", 20)
        marker = json.loads((root / "recovery-exam-reply-withheld.json").read_text())
        attempt_id = marker["attempt_id"]
        before = durable(db, attempt_id)
        report.update(marker=marker, committed_before_retry=before,
                      journal_after_commit=[p.name for p in (root / "durable-actions").glob("*.json")],
                      pending_before_retry=pending(q, quiz_id),
                      browser_response_status=q.js("window.__firstActionStatus"),
                      response_loss_message=q.js("document.getElementById('result').innerText"))
        assert len(before["attempts"]) == 1 and not report["journal_after_commit"]
        assert marker["status_before_drop"] == 200 and report["browser_response_status"] == 500
        assert report["pending_before_retry"]["attempt_id"] == attempt_id
        assert "Retake Exam" not in report["response_loss_message"]

        # Only this synthetic question is edited; its published artifact stays
        # as the browser saw it. The old attempt must remain unaltered.
        with sqlite3.connect(db) as conn:
            question_id = conn.execute(
                "SELECT id FROM questions WHERE quiz_id=? ORDER BY question_number,id LIMIT 1",
                (quiz_id,),
            ).fetchone()[0]
            before_choices = conn.execute("SELECT label,is_correct FROM choices WHERE question_id=? ORDER BY choice_order,id", (question_id,)).fetchall()
            conn.execute("UPDATE choices SET is_correct=1-is_correct WHERE question_id=? AND label IN ('A','B')", (question_id,))
            conn.commit()
            after_choices = conn.execute("SELECT label,is_correct FROM choices WHERE question_id=? ORDER BY choice_order,id", (question_id,)).fetchall()
        report["source_choice_flags_before"] = before_choices
        report["source_choice_flags_after"] = after_choices
        assert before_choices != after_choices
        q.js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('Retry Saving Attempt')).click(); true")
        q.wait("document.getElementById('result')?.innerText.includes('may already have been saved')", 20)
        report["uncertain_message"] = q.js("document.getElementById('result').innerText")
        report["uncertain_screenshot"] = str(q.screenshot("exam-uncertain-result.png"))
        report["pending_after_conflict"] = pending(q, quiz_id)
        report["durable_after_conflict"] = durable(db, attempt_id)
        report["journal_after_conflict"] = [p.name for p in (root / "durable-actions").glob("*.json")]
        assert report["pending_after_conflict"] == report["pending_before_retry"]
        assert report["durable_after_conflict"] == before and not report["journal_after_conflict"]
        assert "Retry Saving Attempt" not in report["uncertain_message"]
        assert "Retake Exam" not in report["uncertain_message"]

        # Reusing the ID with altered summary content is an ordinary conflict,
        # not the specific current-source uncertainty shown above.
        q.js("window.__genericConflict=null; (()=>{const changed=JSON.parse(JSON.stringify(pendingExamAttempt.payload));"
             "changed.score += 1; fetch('/_desktop/recovery/action',{method:'POST',"
             "headers:{'Content-Type':'application/json','X-DLMS-Recovery-Client':'1'},"
             "body:JSON.stringify({kind:'exam',payload:changed,fingerprint:quizContentFingerprint})})"
             ".then(async r=>window.__genericConflict={status:r.status,body:await r.json()});})(); true")
        q.wait("window.__genericConflict !== null", 15)
        report["generic_conflict"] = json.loads(q.js("JSON.stringify(window.__genericConflict)"))
        assert report["generic_conflict"]["status"] == 409
        assert report["generic_conflict"]["body"].get("code") != "exam_existing_unverifiable"

        q.js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('Check This Attempt in History')).click(); true")
        q.wait("location.pathname === '/history' && document.querySelector('.history-result-row.selected') !== null", 20)
        report["history_url"] = q.js("location.href")
        report["history_selected_text"] = q.js("document.querySelector('.history-result-row.selected').innerText")
        report["history_screenshot"] = str(q.screenshot("exam-uncertain-history.png"))
        report["pending_after_history"] = pending(q, quiz_id)
        report["durable_after_history"] = durable(db, attempt_id)
        report["journal_after_history"] = [p.name for p in (root / "durable-actions").glob("*.json")]
        assert f"attempt={attempt_id}" in report["history_url"]
        assert report["pending_after_history"] == report["pending_before_retry"]
        assert report["durable_after_history"] == before and not report["journal_after_history"]
        report["status"] = "pass"
        print(json.dumps({key: value for key, value in report.items() if not key.startswith("durable")}, indent=2))
        return 0
    finally:
        (root / "exam-uncertain-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
