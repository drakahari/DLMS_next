"""Actual Qt stale source after an action failed before backend acceptance."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def rows(db, kind):
    with sqlite3.connect(db) as conn:
        table = "study_responses" if kind == "study" else "attempts"
        return [list(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", choices=("study", "exam"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    root, db = q.paths["root"], q.paths["backend"] / "results.db"
    fixture = json.loads((root / "foundation-create.json").read_text())
    out = {"profile": args.profile, "kind": args.kind}
    try:
        q.go(urlsplit(fixture["quiz_url"]).path)
        if q.js("!!document.querySelector('.quiz-recovery-start-over')"):
            q.js("window.confirm=()=>true;document.querySelector('.quiz-recovery-start-over').click();true")
            q.wait("document.querySelector('.quiz-recovery-panel')?.hidden === true")
        before = rows(db, args.kind)
        out["durable_count_before"] = len(before)
        q.window.interceptor.blocked_internal_paths.add("/_desktop/recovery/action")
        q.js(f"document.querySelector('.{args.kind}-mode-btn').click();true")
        q.wait("document.querySelector('button.choice') !== null")
        q.js("document.querySelector('button.choice').click();true")
        if args.kind == "exam":
            q.js("window.confirm=()=>true;document.getElementById('submitBtn').click();true")
            q.wait("document.getElementById('result')?.innerText.includes('not confirmed as retained or saved')", 20)
            identifier = q.js("pendingExamAttempt?.attemptId")
            out["pre_accept_message"] = q.js("document.getElementById('result').innerText")
            out["pre_accept_retake_hidden"] = "Retake Exam" not in out["pre_accept_message"]
        else:
            q.wait("document.querySelector('#studyLearningEventStatus')?.innerText.includes('awaiting save confirmation')", 20)
            identifier = q.js("[...studyLearningEventSaves.keys()][0]")
            out["pre_accept_message"] = q.js("document.getElementById('studyLearningEventStatus').innerText")
        assert identifier and rows(db, args.kind) == before
        assert not list((root / "durable-actions").glob("*.json"))
        out["action_id"] = identifier
        out["pre_accept_screenshot"] = str(q.screenshot(f"data-safety-{args.kind}-before-accept.png", width=1020, height=760))
        with sqlite3.connect(db) as conn:
            question_id = conn.execute("SELECT id FROM questions WHERE quiz_id=? ORDER BY question_number LIMIT 1", (fixture["quiz_id"],)).fetchone()[0]
            if args.kind == "exam":
                conn.execute("UPDATE choices SET is_correct=1-is_correct WHERE question_id=? AND label IN ('A','B')", (question_id,))
            else:
                conn.execute("UPDATE questions SET question_text=question_text || ' [synthetic stale]' WHERE id=?", (question_id,))
            conn.commit()
        q.window.interceptor.blocked_internal_paths.remove("/_desktop/recovery/action")
        if args.kind == "exam":
            q.js("[...document.querySelectorAll('#result button')].find(b=>b.innerText.includes('Retry Saving Attempt')).click();true")
            q.wait("document.getElementById('result')?.innerText.includes('current source or request content could not be verified')", 20)
            current_id = q.js("pendingExamAttempt?.attemptId")
            out["retry_message"] = q.js("document.getElementById('result').innerText")
            out["history_direction"] = "Check This Attempt in History" in out["retry_message"]
            out["retake_hidden"] = "Retake Exam" not in out["retry_message"]
            out["browser_evidence_before_history"] = q.js(f"localStorage.getItem('dlms.quiz-progress.v1:'+{fixture['quiz_id']})")
        else:
            q.js("document.querySelector('#studyLearningEventStatus .study-learning-save-retry').click();true")
            q.wait("document.querySelector('#studyLearningEventStatus')?.innerText.includes('source revision changed')", 20)
            current_id = q.js("[...studyLearningEventSaves.keys()][0]")
            out["retry_message"] = q.js("document.getElementById('studyLearningEventStatus').innerText")
            out["browser_evidence_after_retry"] = q.js(
                f"localStorage.getItem('dlms.quiz-progress.v1:'+{fixture['quiz_id']})")
            out["browser_evidence_has_action"] = identifier in (out["browser_evidence_after_retry"] or "")
        out.update(same_id=current_id == identifier, rows_unchanged=rows(db, args.kind) == before,
                   journal_empty=not list((root / "durable-actions").glob("*.json")),
                   retry_screenshot=str(q.screenshot(f"data-safety-{args.kind}-stale-retry.png", width=1020, height=760)))
        if args.kind == "exam":
            q.js("[...document.querySelectorAll('#result button')].find(b=>b.innerText.includes('Check This Attempt in History')).click();true")
            q.wait("location.pathname === '/history'", 15)
            out["history_url"] = q.js("location.href")
            out["history_has_attempt"] = identifier in q.js("document.body.innerText")
            out["browser_evidence_after_history"] = q.js(f"localStorage.getItem('dlms.quiz-progress.v1:'+{fixture['quiz_id']})")
            earlier = json.loads(out["browser_evidence_before_history"] or "null")
            later = json.loads(out["browser_evidence_after_history"] or "null")
            out["history_evidence_preserved"] = bool(
                isinstance(earlier, dict) and isinstance(later, dict)
                and earlier.get("pendingAttempt") == later.get("pendingAttempt")
                and earlier.get("session", {}).get("id") == later.get("session", {}).get("id")
                and earlier.get("session", {}).get("ownerToken") == later.get("session", {}).get("ownerToken"))
        out["pass"] = out["same_id"] and out["rows_unchanged"] and out["journal_empty"] and (
            (args.kind == "study" and out["browser_evidence_has_action"]) or (out["pre_accept_retake_hidden"] and out["history_direction"] and out["retake_hidden"]
                                      and not out["history_has_attempt"] and out["history_evidence_preserved"]))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (root / f"data-safety-{args.kind}-stale-before-accept.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({k: out.get(k) for k in ("profile", "kind", "pass", "error", "same_id", "rows_unchanged")}, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
